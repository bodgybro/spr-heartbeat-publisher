#!/usr/bin/env python3
"""One-time Build 700 display/cache label on actual live Bodgybros /sps.
Only index.php and index.html; preserve JS functionality, PDFs, indexes,
Railway updater and encrypted RC1 recovery archive unchanged.
"""
import base64
import hashlib
import io
import os
import posixpath
import paramiko

EXPECT={
    "script.js":"9644c4036cb18107",
    "index.php":"ac7f8408faa333e4",
    "index.html":"6f3888775b76749b",
}
OLD_TITLE='class="build-number">Build 687'
NEW_TITLE='class="build-number">Build 700'
OLD_VERSION="script.js?v=687-retain-last-spr"
NEW_VERSION="script.js?v=700"
def digest(b):return hashlib.sha256(b).hexdigest()
def root_dir():
    root=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
    if root.endswith("/sps/spr"):return root[:-4]
    if root.endswith("/sps"):return root
    if root.endswith("/public_html") or root=="public_html":return root+"/sps"
    raise RuntimeError("Unexpected web root; refusing Build 700")
def read(ftp,path):
    with ftp.open(path,"rb") as f:return f.read()
def write(ftp,path,content):
    with ftp.open(path,"wb") as f:f.write(content)
def patch(data,name):
    text=data.decode("utf-8")
    if text.count(NEW_TITLE)==1 and text.count(NEW_VERSION)==1:
        return data
    if text.count(OLD_TITLE)!=1 or text.count(OLD_VERSION)!=1:
        raise RuntimeError(name+" live 687 build label or script reference has changed")
    return text.replace(OLD_TITLE,NEW_TITLE,1).replace(OLD_VERSION,NEW_VERSION,1).encode("utf-8")
def main():
    keytext=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode("utf-8")
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(keytext));break
        except Exception:pass
    if key is None:raise RuntimeError("Railway SFTP key not available")
    ssh=paramiko.SSHClient()
    ssh.load_host_keys("/data/credentials/spr-sftp-known_hosts")
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ["SFTP_HOST"],port=int(os.environ.get("SFTP_PORT") or 22),
      username=os.environ["SFTP_USERNAME"],pkey=key,allow_agent=False,
      look_for_keys=False,timeout=12,auth_timeout=12,banner_timeout=12)
    ftp=ssh.open_sftp();root=root_dir()
    changes={};original={};staged=[];applied=[]
    try:
        for name in ("script.js","index.php","index.html"):
            data=read(ftp,posixpath.join(root,name))
            if not digest(data).startswith(EXPECT[name]):
                raise RuntimeError("Unexpected live file "+name+" hash "+digest(data)[:16]+"; refusing Build 700")
            original[name]=data
            if name!="script.js":
                changes[name]=patch(data,name)
        for name,data in changes.items():
            dest=posixpath.join(root,name)
            temp=dest+".build700-"+str(os.getpid())
            write(ftp,temp,data)
            if digest(read(ftp,temp))!=digest(data):
                raise RuntimeError("Build 700 SFTP staging checksum failed "+name)
            staged.append((name,temp,dest))
        try:
            for name,temp,dest in staged:
                ftp.posix_rename(temp,dest)
                applied.append(name)
                if digest(read(ftp,dest))!=digest(changes[name]):
                    raise RuntimeError("Build 700 live checksum verification failed "+name)
                print("[BUILD 700 LIVE VERIFIED]",name,digest(changes[name])[:16],flush=True)
            print("[BUILD 700 COMPLETE] Display and browser JS version updated; script.js remains byte-identical, SPR/rosters/RC1 untouched",flush=True)
        except Exception:
            for name in reversed(applied):
                dest=posixpath.join(root,name);temp=dest+".build700-rollback-"+str(os.getpid())
                write(ftp,temp,original[name]);ftp.posix_rename(temp,dest)
                print("[BUILD 700 ROLLED BACK]",name,flush=True)
            raise
    finally:
        for name,temp,dest in staged:
            try:ftp.remove(temp)
            except Exception:pass
        ftp.close()
        ssh.close()
if __name__=="__main__":main()
