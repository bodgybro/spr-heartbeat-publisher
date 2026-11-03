#!/usr/bin/env python3
"""Verify both authenticated sites and catch up recent prepared SPR indexes.

This runs after the new dual-site publisher has installed.
- Both independent host keys pinned; no shared credentials.
- Write+delete a tiny private Kustom smoke file under protected roster cache.
- Compare Driver/Guard PDF source and replica SHA-256 independently.
- Copy up to six recent already-generated Build700 prepared indexes if source
  metadata is role-validated and target PDF SHA matches its source SHA.
- Never change Bodgybros files, indexes, or manifests.
"""
import os,io,base64,posixpath,hashlib,shlex,json,datetime,stat,requests
import paramiko
DATA="/data/credentials/"
TARGET="/home10/kustomvi/public_html/sps"
def log(*x):print("[DUAL SMOKE]",*x,flush=True)
def source_key():
    raw=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode()
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:return typ.from_private_key(io.StringIO(raw))
        except Exception:pass
    raise RuntimeError("Original source SFTP key unavailable")
def connect(host,user,key,kh,port=22):
    client=paramiko.SSHClient()
    client.load_host_keys(kh)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(hostname=host,username=user,port=port,pkey=key,
                   timeout=12,auth_timeout=12,banner_timeout=12,
                   allow_agent=False,look_for_keys=False)
    client.get_transport().set_keepalive(20)
    return client
def root_src():
    root=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
    if root.endswith("/sps/spr"):root=root[:-4]
    elif root.endswith("/public_html"):root+="/sps"
    if not root.endswith("/sps"):raise RuntimeError("Unexpected original SFTP path")
    return root
def shasum(client,path):
    cmd="sha256sum -- "+shlex.quote(path)
    stdin,stdout,stderr=client.exec_command(cmd,timeout=20)
    stdout.channel.settimeout(40)
    line=stdout.read(180).decode(errors="replace")
    rc=stdout.channel.recv_exit_status()
    stdin.close();stdout.close();stderr.close()
    if rc!=0 or len(line)<65:raise RuntimeError("Remote checksum unavailable")
    return line[:64]
def publish(ftp,ssh,path,data,private=False):
    expected=hashlib.sha256(data).hexdigest()
    try:
        if ftp.stat(path).st_size==len(data) and shasum(ssh,path)==expected:
            return "unchanged"
    except FileNotFoundError:pass
    temp=path+".dual-health-tmp"
    try:
        with ftp.open(temp,"wb") as f:
            f.set_pipelined(True)
            f.write(data)
        ftp.chmod(temp,0o600 if private else 0o644)
        if shasum(ssh,temp)!=expected:raise RuntimeError("Staged file SHA mismatch")
        ftp.posix_rename(temp,path)
        if shasum(ssh,path)!=expected:raise RuntimeError("Published file SHA mismatch")
    finally:
        try:ftp.remove(temp)
        except Exception:pass
    return "copied"
src=connect(os.environ["SFTP_HOST"],os.environ["SFTP_USERNAME"],source_key(),
            DATA+"spr-sftp-known_hosts",int(os.environ.get("SFTP_PORT") or 22))
dst=connect("cp-wc18.per01.ds.network","kustomvi",
            paramiko.Ed25519Key.from_private_key_file(DATA+"kustom-transfer/id_ed25519"),
            DATA+"kustom-transfer/known_hosts")
origin=root_src()
try:
 with src.open_sftp() as sftp,dst.open_sftp() as target:
    smoke=posixpath.join(TARGET,".roster-cache",".dual-site-write-smoke")
    raw=b"SPR Search independent Kustom SFTP writing validated on 2026-11-03\n"
    try:
        publish(target,dst,smoke,raw,private=True)
        if shasum(dst,smoke)!=hashlib.sha256(raw).hexdigest():
            raise RuntimeError("Kustom protected folder SHA smoke failed")
        log("KUSTOM PRIVATE WRITE AND SHA VERIFIED")
    finally:
        try:target.remove(smoke)
        except Exception:pass
    matched=0
    for role,label in (("d","Drivers"),("g","Guards")):
        name="All "+label+" Combined 03_11_2026.pdf"
        one=shasum(src,posixpath.join(origin,"spr",role,name))
        other=shasum(dst,posixpath.join(TARGET,"spr",role,name))
        if one!=other:raise RuntimeError("Stored latest "+label+" PDF differs between sites")
        matched+=1
        log("LATEST "+label.upper()+" PDF MATCH VERIFIED",one[:16])
    count=0;no_index=0;skipped=0;bytes_copy=0
    days=[datetime.date(2026,10,29)+datetime.timedelta(days=i) for i in range(6)]
    for day in days:
        date=day.isoformat()
        for role,label in (("d","Drivers"),("g","Guards")):
            base="spr/i/"+role+"/"+date
            mpath=posixpath.join(origin,base+".meta.json")
            gpath=posixpath.join(origin,base+".json.gz")
            try:
                with sftp.open(mpath,"rb") as fh:
                    metadata_raw=fh.read(130000)
                meta=json.loads(metadata_raw)
                stats=sftp.stat(gpath)
            except (FileNotFoundError,ValueError):
                no_index+=1;continue
            if (meta.get("sourceSha") is None or meta.get("roleValidated") is not True or
                meta.get("parserBuild")!=658 or meta.get("pageLayoutBuild")!=595 or
                meta.get("compressedBytes")!=stats.st_size or
                meta.get("role")!=("driver" if role=="d" else "guard") or
                stats.st_size>15*1024*1024):
                skipped+=1;continue
            pdfname="All "+label+" Combined "+day.strftime("%d_%m_%Y")+".pdf"
            pdf_target=posixpath.join(TARGET,"spr",role,pdfname)
            try:
                if shasum(dst,pdf_target)!=meta["sourceSha"]:
                    skipped+=1;continue
            except Exception:skipped+=1;continue
            if bytes_copy+stats.st_size>45*1024*1024:
                skipped+=1;continue
            with sftp.open(gpath,"rb") as srcfile:
                compressed=srcfile.read(stats.st_size+1)
            if len(compressed)!=stats.st_size:raise RuntimeError("Index input size changed")
            directory=posixpath.join(TARGET,"spr","i",role)
            current=TARGET
            for piece in ("spr","i",role):
                current=posixpath.join(current,piece)
                try:target.stat(current)
                except FileNotFoundError:target.mkdir(current)
            result=publish(target,dst,posixpath.join(directory,date+".json.gz"),compressed)
            state=publish(target,dst,posixpath.join(directory,date+".meta.json"),metadata_raw)
            count+=1;bytes_copy+=len(compressed)
            log("PREPARED INDEX",date,role,"data",result,"meta",state,"bytes",len(compressed))
    log("INDEX CATCHUP FINISHED verified",count,"not generated",no_index,"not eligible",skipped,
        "transferred compressed bytes",bytes_copy)
    for host in ("www.kustomvinyls.com","kustomvinyls.com"):
        try:
            r=requests.get("https://"+host+"/sps/",timeout=15,
                           headers={"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 26_2 like Mac OS X) AppleWebKit/605.1.15"},
                           allow_redirects=True)
            log("HTTPS",host,"status",r.status_code,"Build700",("Build 700" in r.text))
        except Exception as e:
            log("HTTPS",host,"FAILED",type(e).__name__,str(e)[:90])
finally:
    src.close();dst.close()
log("SMOKE COMPLETE; both websites unchanged except verified independent Kustom cache and indexes")
