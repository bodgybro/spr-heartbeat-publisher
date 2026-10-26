#!/usr/bin/env python3
"""Live-only narrow Shift 53 timeline fix. Do not touch SPR PDFs/rosters/RC1."""
import base64
import hashlib
import io
import os
import posixpath
import paramiko

OLD="  if(standby)timelineItems.push({type:'standby',standby,order:standby._startIndex});"
NEW=("  if(standby)timelineItems.push({type:'standby',standby,"
     "order:Number.isFinite(standby._startIndex)&&Number.isFinite(shift._sourceStart)"
     "?standby._startIndex-shift._sourceStart:standby._startIndex});")
OLD_CACHE="script.js?v=687"
NEW_CACHE="script.js?v=687-standby-order"
NAME="Build 687"

def sha(payload):return hashlib.sha256(payload).hexdigest()
def root():
    r=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
    if r.endswith("/sps/spr"):return r[:-4]
    if r.endswith("/sps"):return r
    if r.endswith("/public_html") or r=="public_html":return r+"/sps"
    raise RuntimeError("Unrecognised web root")
def read(sftp,p):
    with sftp.open(p,"rb") as f:return f.read()
def save(sftp,p,data):
    with sftp.open(p,"wb") as f:f.write(data)
def update(n,source):
    t=source.decode("utf-8")
    if n=="script.js":
        if NEW in t and OLD not in t:return source
        if t.count(OLD)!=1 or not sha(source).startswith("38318ec40010"):
            raise RuntimeError("Unexpected live Build 687 script; will not overwrite")
        if "function renderShiftCard(shift)" not in t or "function sprOriginalPdfMatchesIndex(" not in t:
            raise RuntimeError("Missing working Build 687 methods; abort")
        return t.replace(OLD,NEW,1).encode("utf-8")
    if NAME not in t:raise RuntimeError("Live build label changed unexpectedly: "+n)
    if NEW_CACHE in t and OLD_CACHE not in t:return source
    if t.count(OLD_CACHE)!=1:raise RuntimeError("Unexpected script version references in "+n)
    return t.replace(OLD_CACHE,NEW_CACHE,1).encode("utf-8")
def main():
    keydata=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode()
    key=None
    for kind in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=kind.from_private_key(io.StringIO(keydata));break
        except Exception:pass
    if key is None:raise RuntimeError("Configured SFTP key unavailable")
    ssh=paramiko.SSHClient()
    ssh.load_host_keys("/data/credentials/spr-sftp-known_hosts")
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ["SFTP_HOST"],username=os.environ["SFTP_USERNAME"],
        port=int(os.environ.get("SFTP_PORT") or 22),pkey=key,
        look_for_keys=False,allow_agent=False,timeout=12,auth_timeout=12,banner_timeout=12)
    ftp=ssh.open_sftp()
    rootdir=root()
    names=("script.js","index.php","index.html")
    originals={};patched={};staged=[];applied=[]
    try:
        for name in names:
            originals[name]=read(ftp,posixpath.join(rootdir,name))
            patched[name]=update(name,originals[name])
        for name in names:
            dest=posixpath.join(rootdir,name)
            tmp=dest+".standby-stage-"+str(os.getpid())
            save(ftp,tmp,patched[name])
            if sha(read(ftp,tmp))!=sha(patched[name]):raise RuntimeError("Staged SHA mismatch: "+name)
            staged.append((name,tmp,dest))
        try:
            for name,tmp,dest in staged:
                if patched[name]==originals[name]:
                    print("[STANDBY ORDER ALREADY CURRENT]",name,flush=True)
                    continue
                ftp.posix_rename(tmp,dest)
                applied.append(name)
                if sha(read(ftp,dest))!=sha(patched[name]):
                    raise RuntimeError("Remote SHA mismatch: "+name)
                print("[STANDBY ORDER LIVE VERIFIED]",name,sha(patched[name])[:16],flush=True)
            print("[STANDBY ORDER FIX DEPLOYED] Only original Shift timeline sort and JS cache key changed",flush=True)
        except Exception:
            for name in reversed(applied):
                dest=posixpath.join(rootdir,name)
                tmp=dest+".standby-rollback-"+str(os.getpid())
                save(ftp,tmp,originals[name])
                ftp.posix_rename(tmp,dest)
                print("[STANDBY ORDER ROLLED BACK]",name,flush=True)
            raise
    finally:
        for _,tmp,_ in staged:
            try:ftp.remove(tmp)
            except Exception:pass
        ftp.close()
        ssh.close()
if __name__=="__main__":main()
