#!/usr/bin/env python3
"""Build 700 dual-site SPR + roster publisher; apply last, before py_compile.

Extend the currently working updater without replacing it:
- The existing Bodgybros SFTP/cPanel uploader and roster validation stay intact.
- The separately authorized Kustom SSH key lives ONLY on the Railway volume.
- Independently transfer every downloaded SPR and roster PDF to Kustom via
  atomic SHA-256 checked SFTP and independently publish roster manifest.
- Dual prepared indexes use the same validated source hash and parser schema.
- Preserve all four Australia/Sydney updater slots and existing PDF cache.
- Report an incomplete update if EITHER site's storage cannot be verified.
"""
import ast
from pathlib import Path
import sys

MARKER="# SPR_DUAL_SITE_INDEPENDENT_SFTP_20261103"
EXTENSION=r'''
# SPR_DUAL_SITE_INDEPENDENT_SFTP_20261103
# The current primary site remains untouched. Kustom SSH key is persisted at
# /data/credentials/kustom-transfer/id_ed25519, *never* in app source or Railway env.
import hashlib as _dual_sha
import posixpath as _dual_path
import re as _dual_re
import shlex as _dual_shlex
import stat as _dual_stat
import threading as _dual_threading
import time as _dual_time
from pathlib import Path as _dual_Path

_DUAL_KUSTOM_HOST="cp-wc18.per01.ds.network"
_DUAL_KUSTOM_USER="kustomvi"
_DUAL_KUSTOM_ROOT="/home10/kustomvi/public_html/sps"
_DUAL_KUSTOM_PORT=22
_DUAL_SFTP_TLS=_dual_threading.local()
_DUAL_SITE_SPR_TLS=_dual_threading.local()
_DUAL_SITE_ROSTER_TLS=_dual_threading.local()
_DUAL_PDF_PRIMARY=upload_pdf
_DUAL_ROSTER_PRIMARY=upload_cached_roster_pdf
_DUAL_MANIFEST_PRIMARY=publish_roster_manifest
_DUAL_ROSTER_SYNC_PRIMARY=sync_all_rosters_online
_DUAL_SPR_UPDATE_PRIMARY=run_update
_DUAL_INDEX_PRIMARY_CURRENT=_spr_primary_index_current
_DUAL_INDEX_PRIMARY_PUBLISH=_spr_publish_index_primary_sftp
_DUAL_INDEX_BACKGROUND_PRIMARY=_spr_index_background

def _dual_enabled():
    return str(os.environ.get("SPR_DUAL_SITE_ENABLED","1")).strip()=="1"

def _dual_kustom_open():
    import paramiko
    key_file=DATA_ROOT/"credentials"/"kustom-transfer"/"id_ed25519"
    known=DATA_ROOT/"credentials"/"kustom-transfer"/"known_hosts"
    if not key_file.is_file() or not known.is_file():
        raise RuntimeError("Authorized Kustom SSH credentials unavailable on Railway volume")
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(known))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=_DUAL_KUSTOM_HOST,username=_DUAL_KUSTOM_USER,
                port=_DUAL_KUSTOM_PORT,
                pkey=paramiko.Ed25519Key.from_private_key_file(str(key_file)),
                timeout=12,auth_timeout=12,banner_timeout=12,
                look_for_keys=False,allow_agent=False)
    ssh.get_transport().set_keepalive(25)
    ftp=ssh.open_sftp()
    ftp.get_channel().settimeout(75)
    if not _dual_stat.S_ISDIR(ftp.stat(_DUAL_KUSTOM_ROOT).st_mode):
        ssh.close()
        raise RuntimeError("Kustom destination site root no longer exists")
    return ssh,ftp

def _dual_connection():
    cached=getattr(_DUAL_SFTP_TLS,"session",None)
    if cached is not None:
        return cached
    cached=_dual_kustom_open()
    _DUAL_SFTP_TLS.session=cached
    _DUAL_SFTP_TLS.directories=set()
    return cached

def _dual_release_connection():
    session=getattr(_DUAL_SFTP_TLS,"session",None)
    _DUAL_SFTP_TLS.session=None
    _DUAL_SFTP_TLS.directories=set()
    if session is not None:
        ssh,ftp=session
        try:ftp.close()
        except Exception:pass
        try:ssh.close()
        except Exception:pass

def _dual_rel(relative):
    if not isinstance(relative,str) or relative.startswith("/"):
        raise RuntimeError("Invalid relative Kustom site file path")
    pieces=relative.split("/")
    if (not pieces or any(not x or x in (".","..") or
        not _dual_re.fullmatch(r"[A-Za-z0-9._ -]+",x) for x in pieces)):
        raise RuntimeError("Unsafe Kustom relative file path")
    result=_dual_path.normpath(_dual_path.join(_DUAL_KUSTOM_ROOT,*pieces))
    if not result.startswith(_DUAL_KUSTOM_ROOT+"/"):
        raise RuntimeError("Kustom site path escaped web root")
    return result

def _dual_remote_sha(ssh,ftp,remote):
    # Server-side hashing prevents 78 repeated 1MB downloads for verification.
    try:
        cmd="sha256sum -- "+_dual_shlex.quote(remote)
        stdin,stdout,stderr=ssh.exec_command(cmd,timeout=18)
        stdout.channel.settimeout(35)
        out=stdout.read(190).decode("ascii",errors="replace")
        rc=stdout.channel.recv_exit_status()
        stdin.close();stdout.close();stderr.close()
        if rc==0 and _dual_re.match(r"^[0-9a-f]{64}  ",out):
            return out[:64]
    except Exception:
        pass
    digest=_dual_sha.sha256()
    with ftp.open(remote,"rb") as inp:
        try:inp.prefetch(max_concurrent_requests=24)
        except Exception:pass
        while True:
            b=inp.read(1024*1024)
            if not b:break
            digest.update(b)
    return digest.hexdigest()

def _dual_store(relative,data,mode=0o644):
    if not isinstance(data,(bytes,bytearray)) or not data:
        raise RuntimeError("Empty/non-bytes Kustom site upload")
    data=bytes(data)
    ssh,ftp=_dual_connection()
    target=_dual_rel(relative)
    current=_DUAL_KUSTOM_ROOT
    for segment in relative.split("/")[:-1]:
        current=_dual_path.join(current,segment)
        if current not in _DUAL_SFTP_TLS.directories:
            try:
                if not _dual_stat.S_ISDIR(ftp.stat(current).st_mode):
                    raise RuntimeError("Unexpected non-directory Kustom storage path")
            except FileNotFoundError:
                ftp.mkdir(current,0o700 if segment==".roster-cache" else 0o755)
            _DUAL_SFTP_TLS.directories.add(current)
    expected=_dual_sha.sha256(data).hexdigest()
    try:
        st=ftp.stat(target)
        if st.st_size==len(data) and _dual_remote_sha(ssh,ftp,target)==expected:
            return "unchanged",expected
    except FileNotFoundError:
        pass
    temp=target+".dual-stage-"+str(os.getpid())+"-"+str(_dual_threading.get_ident())
    try:
        with ftp.open(temp,"wb") as outfile:
            outfile.set_pipelined(True)
            for offset in range(0,len(data),1024*1024):
                outfile.write(data[offset:offset+1024*1024])
        ftp.chmod(temp,mode)
        if ftp.stat(temp).st_size!=len(data):
            raise RuntimeError("Kustom staged file length mismatch: "+relative)
        if _dual_remote_sha(ssh,ftp,temp)!=expected:
            raise RuntimeError("Kustom staged SHA-256 mismatch: "+relative)
        ftp.posix_rename(temp,target)
        if _dual_remote_sha(ssh,ftp,target)!=expected:
            raise RuntimeError("Kustom published SHA-256 mismatch: "+relative)
    except Exception:
        _dual_release_connection()
        raise
    finally:
        try:ftp.remove(temp)
        except Exception:pass
    return "uploaded",expected

def _dual_upload_kustom_pdf(role,pdf):
    if role not in ("drivers","guards"):
        raise RuntimeError("Invalid driver/guard role for Kustom")
    name=_dual_Path(pdf).name
    expected="Drivers" if role=="drivers" else "Guards"
    if not _dual_re.fullmatch(r"All "+expected+r" Combined \d{2}_\d{2}_20\d{2}\.pdf",name):
        raise RuntimeError("Kustom SPR role or file date mismatch: "+name)
    raw=_dual_Path(pdf).read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise RuntimeError("Kustom SPR source not a PDF")
    role_dir="d" if role=="drivers" else "g"
    status,sha=_dual_store("spr/"+role_dir+"/"+name,raw)
    print("  [DUAL KUSTOM SPR VERIFIED] "+name+" "+status+" "+sha[:12],flush=True)
    return status,sha

def upload_pdf(site,role,pdf,cfg,page=None):
    if not _dual_enabled():
        return _DUAL_PDF_PRIMARY(site,role,pdf,cfg,page)
    name=_dual_Path(pdf).name
    if role not in ("drivers","guards"):
        return _DUAL_PDF_PRIMARY(site,role,pdf,cfg,page)
    # The source role verifier is already used for primary uploads. Also
    # validate before independently sending any PDF to the secondary site.
    if "_spr686_check_pdf_role" in globals():
        _spr686_check_pdf_role(pdf,role)
    ok={};fail={}
    try:
        ok["bodgybros"]=_DUAL_PDF_PRIMARY(site,role,pdf,cfg,page)
    except Exception as exc:
        fail["bodgybros"]=str(exc)[:240]
        print("  [DUAL SPR PRIMARY FAILED] "+name+": "+fail["bodgybros"],flush=True)
    try:
        ok["kustom"],sha=_dual_upload_kustom_pdf(role,pdf)
    except Exception as exc:
        fail["kustom"]=str(exc)[:240]
        _dual_release_connection()
        print("  [DUAL SPR KUSTOM FAILED] "+name+": "+fail["kustom"],flush=True)
    else:
        # If original was unreachable, the prepared index still needs a job.
        mat=_dual_re.fullmatch(r"All (Drivers|Guards) Combined (\d\d)_(\d\d)_(20\d\d)\.pdf",name)
        if mat and "bodgybros" not in ok:
            date=f"{mat[4]}-{mat[3]}-{mat[2]}"
            role_name="driver" if role=="drivers" else "guard"
            with _SPR_INDEX_LOCK:
                _SPR_INDEX_QUEUE[(date,role_name)]={
                    "date":date,"role":role_name,"sha":sha,
                    "site":"https://www.kustomvinyls.com/sps"}
    if fail:
        issues=getattr(_DUAL_SITE_SPR_TLS,"issues",None)
        if issues is not None:
            issues.extend(f"{name} {label}: {message}" for label,message in fail.items())
        print("  [DUAL SPR PARTIAL] "+name+" "+",".join(fail),flush=True)
    if not ok:
        raise RuntimeError("SPR missing on both sites: "+name+"; "+str(fail)[:260])
    if fail and getattr(_DUAL_SITE_SPR_TLS,"issues",None) is None:
        raise RuntimeError("SPR upload incomplete on one site: "+name+"; "+str(fail)[:260])
    return ok.get("bodgybros") or {"ok":True,"method":"Kustom SFTP","sites":list(ok)}

def run_update(site,*args,**kwargs):
    if not _dual_enabled():
        return _DUAL_SPR_UPDATE_PRIMARY(site,*args,**kwargs)
    _DUAL_SITE_SPR_TLS.issues=[]
    try:
        result=_DUAL_SPR_UPDATE_PRIMARY(site,*args,**kwargs)
        issues=_DUAL_SITE_SPR_TLS.issues
        if issues:
            raise RuntimeError("SPR update incomplete on two destinations: "+" | ".join(issues)[:500])
        print("[DUAL SPR COMPLETE] Both destinations verified for all uploaded PDFs",flush=True)
        return result
    finally:
        _DUAL_SITE_SPR_TLS.issues=None
        _dual_release_connection()

def _dual_kustom_index_current(date,role,sha):
    if role not in ("driver","guard"):raise RuntimeError("Invalid SPR index role")
    ssh,ftp=_dual_connection()
    base="spr/i/"+("d" if role=="driver" else "g")+"/"+date
    try:
        with ftp.open(_dual_rel(base+".meta.json"),"rb") as stream:
            meta=json.loads(stream.read(120000).decode("utf-8"))
        gz=ftp.stat(_dual_rel(base+".json.gz"))
        return (meta.get("sourceSha")==sha and meta.get("parserBuild")==658 and
            meta.get("pageLayoutBuild")==595 and meta.get("roleValidated") is True and
            meta.get("compressedBytes")==gz.st_size and gz.st_size>0)
    except FileNotFoundError:
        return False

def _spr_primary_index_current(date,role,sha):
    if not _dual_enabled():
        return _DUAL_INDEX_PRIMARY_CURRENT(date,role,sha)
    primary=False;second=False
    try:primary=_DUAL_INDEX_PRIMARY_CURRENT(date,role,sha)
    except Exception as exc:
        print("  [DUAL PRIMARY INDEX CHECK FAILED] "+str(exc)[:140],flush=True)
    try:second=_dual_kustom_index_current(date,role,sha)
    except Exception as exc:
        _dual_release_connection()
        print("  [DUAL KUSTOM INDEX CHECK FAILED] "+str(exc)[:140],flush=True)
    if primary and second:
        print("  [DUAL INDEXES CURRENT] "+date+" "+role,flush=True)
    return primary and second

def _spr_publish_index_primary_sftp(date,role,source_sha,compressed):
    if not _dual_enabled():
        return _DUAL_INDEX_PRIMARY_PUBLISH(date,role,source_sha,compressed)
    err={};ok={}
    try:
        ok["bodgybros"]=_DUAL_INDEX_PRIMARY_PUBLISH(date,role,source_sha,compressed)
    except Exception as exc:
        err["bodgybros"]=str(exc)[:160]
    try:
        folder="d" if role=="driver" else "g"
        pdf_name=("All Drivers Combined " if role=="driver" else "All Guards Combined ")+date[8:10]+"_"+date[5:7]+"_"+date[:4]+".pdf"
        pdf_remote=_dual_rel("spr/"+folder+"/"+pdf_name)
        ssh,ftp=_dual_connection()
        if _dual_remote_sha(ssh,ftp,pdf_remote)!=source_sha:
            raise RuntimeError("Kustom prepared index PDF source SHA-256 does not match")
        base="spr/i/"+folder+"/"+date
        st,_=_dual_store(base+".json.gz",compressed)
        metadata={
            "ok":True,"date":date,"role":role,"sourceSha":source_sha,
            "parserBuild":658,"pageLayoutBuild":595,
            "updatedAt":int(_dual_time.time()),"compressedBytes":len(compressed),
            "roleValidated":True}
        ms,_=_dual_store(base+".meta.json",json.dumps(metadata,separators=(",",":")).encode("utf-8"))
        ok["kustom"]=st
        print("  [DUAL KUSTOM INDEX VERIFIED] "+date+" "+role+" "+st+" meta "+ms,flush=True)
    except Exception as exc:
        err["kustom"]=str(exc)[:180]
        _dual_release_connection()
    if err:
        print("  [DUAL INDEX PARTIAL] "+date+" "+role+" "+str(err)[:400],flush=True)
    if err:
        raise RuntimeError("Prepared index incomplete across the two websites: "+str(err)[:400])
    if not ok:
        raise RuntimeError("Prepared indexes failed on both websites: "+str(err)[:400])
    return ok.get("bodgybros")

def _spr_index_background(jobs):
    try:
        return _DUAL_INDEX_BACKGROUND_PRIMARY(jobs)
    finally:
        _dual_release_connection()

def upload_cached_roster_pdf(url,name,data,cache_path=""):
    if not _dual_enabled():
        return _DUAL_ROSTER_PRIMARY(url,name,data,cache_path)
    _roster_sftp_check_url(url)
    parts=_roster_valid_cache_path(cache_path)
    if not isinstance(data,(bytes,bytearray)) or not data.startswith(b"%PDF-") or name!=parts[-1]:
        raise RuntimeError("Invalid roster data or filename: "+str(name)[:120])
    ok={};fail={}
    try:ok["bodgybros"]=_DUAL_ROSTER_PRIMARY(url,name,data,cache_path)
    except Exception as exc:
        fail["bodgybros"]=str(exc)[:150]
        print("    [DUAL ROSTER PRIMARY FAILED] "+str(name)[:100]+": "+fail["bodgybros"],flush=True)
    try:
        state,sha=_dual_store("rosters/"+cache_path,bytes(data))
        if not hasattr(_DUAL_SITE_ROSTER_TLS,"proofs"):
            _DUAL_SITE_ROSTER_TLS.proofs={}
        _DUAL_SITE_ROSTER_TLS.proofs[url]=(cache_path,len(data),sha)
        ok["kustom"]={"ok":True,"complete":True,"changed":state!="unchanged",
                       "bytes":len(data),"sha256":sha}
        print("    [DUAL KUSTOM ROSTER VERIFIED] "+cache_path+" "+state+" "+sha[:12],flush=True)
    except Exception as exc:
        fail["kustom"]=str(exc)[:170]
        _dual_release_connection()
        print("    [DUAL ROSTER KUSTOM FAILED] "+str(name)[:100]+": "+fail["kustom"],flush=True)
    for host,msg in fail.items():
        problems=getattr(_DUAL_SITE_ROSTER_TLS,"issues",None)
        if problems is not None:problems.setdefault(host,[]).append(str(name)[:60]+": "+msg)
    if not ok:
        raise RuntimeError("Roster missing from both websites: "+str(name)[:100])
    return ok.get("bodgybros") or ok["kustom"]

def publish_roster_manifest(root_url,entries):
    if not _dual_enabled():
        return _DUAL_MANIFEST_PRIMARY(root_url,entries)
    if not isinstance(entries,list):raise RuntimeError("Roster manifest entries missing")
    folders=[e for e in entries if e.get("kind")=="folder" and e.get("parent_url")==root_url]
    pdfs=[e for e in entries if e.get("kind")=="pdf"]
    if len(folders)!=13 or len(pdfs)!=78:
        raise RuntimeError("Incomplete roster discovery; old manifests preserved: "+str(len(folders))+" depots / "+str(len(pdfs))+" PDFs")
    proofs=getattr(_DUAL_SITE_ROSTER_TLS,"proofs",{})
    ok={};errors={}
    try:
        ok["bodgybros"]=_DUAL_MANIFEST_PRIMARY(root_url,entries)
    except Exception as exc:
        errors["bodgybros"]=str(exc)[:240]
    try:
        if len(proofs)!=len(pdfs):
            raise RuntimeError("Kustom roster PDF proof count "+str(len(proofs))+"/"+str(len(pdfs)))
        paths=set()
        ssh,ftp=_dual_connection()
        for entry in pdfs:
            path=entry.get("cache_path")
            parts=_roster_valid_cache_path(path)
            proof=proofs.get(entry.get("url"))
            if not proof or proof[0]!=path or proof[1]<100 or path in paths:
                raise RuntimeError("Kustom roster proof missing/duplicate: "+str(path)[:120])
            paths.add(path)
            st=ftp.stat(_dual_rel("rosters/"+path))
            if st.st_size!=proof[1]:
                raise RuntimeError("Kustom roster remote PDF size mismatch: "+path)
        # Protect manifest contents; use current source URL entries as cache keys.
        # Each physical SFTP file is already independently SHA-256 verified.
        try:ftp.stat(_dual_rel(".roster-cache/.htaccess"))
        except FileNotFoundError:
            _dual_store(".roster-cache/.htaccess",b"Require all denied\nDeny from all\n",0o644)
        payload={"root":root_url,"generated":int(_dual_time.time()),"entries":entries}
        state,sha=_dual_store(".roster-cache/manifest.json",
                     json.dumps(payload,separators=(",",":"),ensure_ascii=False).encode("utf-8"),0o600)
        ok["kustom"]={"ok":True,"entries":len(entries),"pdfs":len(pdfs),"method":"Kustom SFTP"}
        print("  [DUAL KUSTOM MANIFEST VERIFIED] "+str(len(pdfs))+
              " PDFs / "+str(len(folders))+" depots, "+state+" "+sha[:12],flush=True)
    except Exception as exc:
        errors["kustom"]=str(exc)[:240]
        _dual_release_connection()
    site_issues=getattr(_DUAL_SITE_ROSTER_TLS,"issues",{})
    for host,problems in site_issues.items():
        if problems and host not in errors:
            errors[host]=str(len(problems))+" per-file upload failure(s): "+str(problems[0])[:170]
    if errors:
        print("[DUAL ROSTER INCOMPLETE] "+str(errors)[:500],flush=True)
        # Mark incomplete, even if Kustom worked but the primary did not.
        raise RuntimeError("Both roster stores must be complete: "+str(errors)[:500])
    print("[DUAL ROSTER COMPLETE] Both independent stores have 78 roster PDFs",flush=True)
    return ok.get("bodgybros") or ok["kustom"]

def sync_all_rosters_online():
    if not _dual_enabled():
        return _DUAL_ROSTER_SYNC_PRIMARY()
    _DUAL_SITE_ROSTER_TLS.proofs={}
    _DUAL_SITE_ROSTER_TLS.issues={"bodgybros":[],"kustom":[]}
    try:
        return _DUAL_ROSTER_SYNC_PRIMARY()
    finally:
        _dual_release_connection()
        _DUAL_SITE_ROSTER_TLS.proofs={}
        _DUAL_SITE_ROSTER_TLS.issues={}

print("[DUAL SITE READY] Independent Bodgybros + Kustom SFTP uploads active; 08/12/16/22 Sydney scheduler unchanged",flush=True)
'''

def apply(path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:
        print("[DUAL SITE] Patch already present",flush=True)
        return
    required=(
        "# SPR_ROSTER_SFTP_PUBLISH_VERIFIED_20261101",
        "# SPR_ROSTER_SFTP_CONNECTION_REUSE_20261101",
        "# SPR_SCHEDULE_08_12_16_22_700",
        "# SPR_SINGLE_SITE_BODGYBROS_674",
    )
    for marker in required:
        if marker not in source:
            raise RuntimeError("Working Build 700 component absent: "+marker)
    tree=ast.parse(source)
    functions={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
    expected={"upload_pdf","upload_cached_roster_pdf","publish_roster_manifest",
              "sync_all_rosters_online","run_update","_spr_primary_index_current",
              "_spr_publish_index_primary_sftp","_roster_sftp_check_url",
              "_roster_valid_cache_path","_spr_index_background"}
    missing=expected-functions
    if missing:raise RuntimeError("Dual publisher base functions missing: "+str(sorted(missing)))
    # Kustom never inherits source credentials or website paths.
    if "SFTP_HOST" in EXTENSION or "SFTP_PRIVATE_KEY_B64" in EXTENSION:
        raise RuntimeError("Cannot mix Bodgybros credentials into Kustom publisher")
    mains=[n for n in tree.body if isinstance(n,ast.If) and
        ("__name__" in (ast.get_source_segment(source,n.test) or ""))]
    if not mains:raise RuntimeError("Updater main boundary not found")
    # Preserve primary fast index page; only fall back to Kustom when the
    # original site's public page cannot load (DNS outage, TLS, etc.).
    primary_index_fragment=(
        "    site='https://www.bodgybros.com/sps'\n"
        "    page.goto(site+'/',wait_until='domcontentloaded',timeout=45000)\n"
        "    page.wait_for_function('typeof window.__SPR_INDEXER_API?.build === \"function\"',timeout=25000)\n")
    fallback_index_fragment=(
        "    site='https://www.bodgybros.com/sps'\n"
        "    try:\n"
        "        page.goto(site+'/',wait_until='domcontentloaded',timeout=45000)\n"
        "        page.wait_for_function('typeof window.__SPR_INDEXER_API?.build === \"function\"',timeout=25000)\n"
        "    except Exception as original_error:\n"
        "        print('  [DUAL INDEX PAGE FALLBACK] Bodgybros unavailable: '+str(original_error)[:120],flush=True)\n"
        "        site='https://www.kustomvinyls.com/sps'\n"
        "        page.goto(site+'/',wait_until='domcontentloaded',timeout=45000)\n"
        "        page.wait_for_function('typeof window.__SPR_INDEXER_API?.build === \"function\"',timeout=25000)\n")
    index_nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_spr_publish_index"]
    if not index_nodes:
        raise RuntimeError("Expected background SPR index builder missing")
    index_node=index_nodes[-1]
    current_index="".join(source.splitlines(keepends=True)[index_node.lineno-1:index_node.end_lineno])
    if current_index.count(primary_index_fragment)!=1:
        raise RuntimeError("Current Build700 index page navigation differed; refusing unsafe fallback")
    source=source.replace(primary_index_fragment,fallback_index_fragment,1)
    tree=ast.parse(source)
    mains=[n for n in tree.body if isinstance(n,ast.If) and
        ("__name__" in (ast.get_source_segment(source,n.test) or ""))]
    target=mains[-1].lineno-1
    lines=source.splitlines(keepends=True)
    revised="".join(lines[:target])+EXTENSION+"\n"+"".join(lines[target:])
    compile(revised,str(path),"exec")
    if revised.count(MARKER)!=1:raise RuntimeError("Dual patch marker not unique")
    tmp=path.with_suffix(path.suffix+".dual-staged")
    tmp.write_text(revised,encoding="utf-8")
    tmp.replace(path)
    print("[DUAL SITE PATCH APPLIED] Both hosts independent, every SPR+roster SHA verified, manifests guarded",flush=True)

if __name__=="__main__":
    apply(Path(sys.argv[1]))
