#!/usr/bin/env python3
"""SPR Online Updater: upload PDFs over SFTP, then cPanel UAPI fallback.

Apply after existing Cloudflare, roster and schedule patches. Bodgybros PDFs
are transferred and verified using SFTP, with direct cPanel UAPI fallback.
"""
import ast
from pathlib import Path
import sys

HELPERS=r'''
# Direct upload helpers: the sensitive settings are read only from Railway env.
_SPR_SFTP_RETRY_AFTER = 0

def _spr_remote_subdir(root, role):
    import posixpath
    root=str(root or "").replace("\\", "/").rstrip("/")
    sub="d" if role=="drivers" else "g"
    if root.endswith("/sps/spr"):
        return posixpath.join(root,sub)
    if root.endswith("/sps"):
        return posixpath.join(root,"spr",sub)
    if root.endswith("/public_html") or root=="public_html":
        return posixpath.join(root,"sps","spr",sub)
    if root.endswith("/sps/spr/d") or root.endswith("/sps/spr/g"):
        return posixpath.join(root.rsplit("/",1)[0],sub)
    raise RuntimeError("SFTP_ROOT must end in public_html, sps, or sps/spr")

def _spr_upload_over_sftp(role, pdf):
    """Atomic upload, preserving SharePoint credentials and website paths."""
    import base64
    import io
    import posixpath
    import paramiko
    global _SPR_SFTP_RETRY_AFTER
    now=time.monotonic()
    if now < _SPR_SFTP_RETRY_AFTER:
        raise RuntimeError("SFTP connection unavailable (cooldown)")
    host=os.environ.get("SFTP_HOST","").strip()
    user=os.environ.get("SFTP_USERNAME","").strip()
    port=int(os.environ.get("SFTP_PORT") or 22)
    rawkey=os.environ.get("SFTP_PRIVATE_KEY_B64","").strip()
    root=os.environ.get("SFTP_ROOT","").strip()
    if not (host and user and rawkey and root):
        raise RuntimeError("SFTP_HOST, SFTP_USERNAME, SFTP_PRIVATE_KEY_B64 and SFTP_ROOT must be set")
    filename=Path(pdf).name
    import re as _re
    if not _re.fullmatch(r"All (Drivers|Guards) Combined \d{2}_\d{2}_\d{4}\.pdf",filename):
        raise RuntimeError("Unexpected SPR filename")
    if (role=="drivers" and "Drivers" not in filename) or (role=="guards" and "Guards" not in filename):
        raise RuntimeError("SPR role/filename mismatch")
    remote_dir=_spr_remote_subdir(root,role)
    # Keep the accepted host key in persistent /data so later key changes
    # are rejected by Paramiko. First use is trust-on-first-use.
    kh=DATA_ROOT/"credentials"/"spr-sftp-known_hosts"
    kh.parent.mkdir(parents=True,exist_ok=True)
    if not kh.exists():
        kh.write_text("",encoding="ascii")
    os.chmod(kh,0o600)
    keytext=base64.b64decode(rawkey).decode("utf-8")
    key=None
    for keytype in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:
            key=keytype.from_private_key(io.StringIO(keytext))
            break
        except Exception:
            continue
    if key is None:
        raise RuntimeError("SFTP private key could not be parsed")
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(kh))
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    tmp=None
    try:
        ssh.connect(hostname=host,port=port,username=user,pkey=key,
                    timeout=7,auth_timeout=8,banner_timeout=8,
                    allow_agent=False,look_for_keys=False)
        ssh.save_host_keys(str(kh))
        sftp=ssh.open_sftp()
        try:
            import stat
            if not stat.S_ISDIR(sftp.stat(remote_dir).st_mode):
                raise RuntimeError("Remote SPR directory is not a folder: "+remote_dir)
            remote=posixpath.join(remote_dir,filename)
            tmp=remote+".updating-"+str(os.getpid())
            sftp.put(str(pdf),tmp,confirm=True)
            if sftp.stat(tmp).st_size!=Path(pdf).stat().st_size:
                raise RuntimeError("SFTP uploaded file size does not match")
            # cPanel/OpenSSH supports posix-rename extension for replacing
            # existing files atomically. Do not remove old files on failure.
            sftp.posix_rename(tmp,remote)
            tmp=None
            if sftp.stat(remote).st_size!=Path(pdf).stat().st_size:
                raise RuntimeError("SFTP final file size does not match")
            # Verify the actual remote bytes over SFTP; HTTP endpoint checks
            # must never determine success for the primary website.
            import hashlib
            with Path(pdf).open("rb") as inp:
                local_sha=hashlib.file_digest(inp,"sha256").hexdigest()
            remote_hash=hashlib.sha256()
            with sftp.open(remote,"rb") as remote_input:
                while True:
                    block=remote_input.read(1024*1024)
                    if not block: break
                    remote_hash.update(block)
            if remote_hash.hexdigest()!=local_sha:
                raise RuntimeError("SFTP remote PDF SHA-256 mismatch")
            print("  [SFTP PDF VERIFIED] "+filename+" "+local_sha[:12],flush=True)
        finally:
            if tmp:
                try: sftp.remove(tmp)
                except Exception: pass
            sftp.close()
    except Exception:
        _SPR_SFTP_RETRY_AFTER=time.monotonic()+300
        raise
    finally:
        ssh.close()
    return {"ok":True,"method":"SFTP","filename":filename,"directory":remote_dir}

def _spr_upload_over_cpanel(role, pdf):
    """Direct cPanel UAPI on port 2083; never the public website upload endpoint."""
    host=(os.environ.get("CPANEL_HOST") or "").strip()
    user=(os.environ.get("CPANEL_USERNAME") or "").strip()
    token=(os.environ.get("CPANEL_API_TOKEN") or "").strip()
    port=int(os.environ.get("CPANEL_PORT") or 2083)
    webroot=(os.environ.get("CPANEL_WEB_ROOT") or "public_html/sps").strip().rstrip("/")
    if not (host and user and token):
        raise RuntimeError("cPanel fallback requires CPANEL_HOST, CPANEL_USERNAME and CPANEL_API_TOKEN")
    from urllib.parse import urlparse as _urlparse
    parsed=_urlparse(host if "://" in host else "https://"+host)
    host=parsed.hostname
    dest=webroot+"/spr/"+("d" if role=="drivers" else "g")
    verify=str(os.environ.get("CPANEL_VERIFY_SSL","1")).strip().lower() not in ("0","false","no")
    url=f"https://{host}:{port}/execute/Fileman/upload_files"
    with Path(pdf).open("rb") as f:
        r=requests.post(url,
             headers={"Authorization":f"cpanel {user}:{token}"},
             data={"dir":dest,"overwrite":"1"},
             files={"file-1":(Path(pdf).name,f,"application/pdf")},
             timeout=(12,150),verify=verify)
    r.raise_for_status()
    try: j=r.json()
    except Exception: raise RuntimeError("cPanel returned non-JSON response (HTTP "+str(r.status_code)+")")
    if not isinstance(j,dict) or j.get("status") not in (1,True,"1") or j.get("errors"):
        raise RuntimeError("cPanel upload rejected: "+str(j.get("errors") or j.get("messages") or j.get("status"))[:250])
    return {"ok":True,"method":"cPanel UAPI","filename":Path(pdf).name,"directory":dest}

def upload_pdf(site, role, pdf, cfg, page=None):
    if role not in ("drivers","guards"):
        raise RuntimeError("Unexpected SPR directory: "+str(role))
    raw=os.environ.get("SPR_UPLOAD_TARGETS") or str(site or cfg.get("relay_site_url") or "https://bodgybros.com/sps")
    targets=[]
    for value in raw.split(","):
        target=canonical_spr_site(value.strip())
        if target and target not in targets: targets.append(target)
    if not targets: targets=["https://bodgybros.com/sps"]
    errors=[]
    results={}
    for target in targets:
        domain=(urlparse(target).hostname or "").lower()
        label=domain or target
        print(f"  [UPLOAD] {label}: {Path(pdf).name}",flush=True)
        if domain in ("bodgybros.com","www.bodgybros.com"):
            try:
                result=_spr_upload_over_sftp(role,pdf)
                print(f"  [UPLOADED SFTP] {label}: {Path(pdf).name}",flush=True)
            except Exception as sftp_error:
                print("  [SFTP UNAVAILABLE] "+str(sftp_error)[:250]+"; trying direct cPanel API",flush=True)
                try:
                    result=_spr_upload_over_cpanel(role,pdf)
                    print(f"  [UPLOADED CPANEL] {label}: {Path(pdf).name}",flush=True)
                except Exception as cpanel_error:
                    errors.append(label+": SFTP "+str(sftp_error)[:140]+"; cPanel "+str(cpanel_error)[:250])
                    continue
        else:
            # Retain pre-existing secondary-site behaviour.
            try:
                result=_upload_pdf_to_site(target,role,pdf,cfg,page)
                print(f"  [UPLOADED] {label}: {Path(pdf).name}",flush=True)
            except Exception as ex:
                errors.append(label+": "+str(ex)[:250])
                continue
        results[label]=result
    if errors:
        raise RuntimeError(" | ".join(errors))
    return results
'''

def main(path):
    src=path.read_text(encoding="utf-8")
    if "# SPR_SFTP_FIRST_CPANEl_FALLBACK" in src:
        print("SFTP upload patch already installed")
        return
    tree=ast.parse(src)
    matches=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="upload_pdf"]
    if len(matches)!=1:
        raise SystemExit("Cannot find exactly one upload_pdf() function")
    node=matches[0]
    lines=src.splitlines(keepends=True)
    src=("".join(lines[:node.lineno-1])+
         "\n# SPR_SFTP_FIRST_CPANEl_FALLBACK\n"+HELPERS+"\n"+
         "".join(lines[node.end_lineno:]))
    compile(src,str(path),"exec")
    path.write_text(src,encoding="utf-8")
    print("SPR upload method: SFTP first; direct cPanel UAPI fallback; no PHP upload for bodgybros")

if __name__=="__main__":
    main(Path(sys.argv[1]))
