#!/usr/bin/env python3
"""One-time RC1 on Bodgybros: live label, paths.txt and live-root ZIP."""
import os,io,base64,hashlib,posixpath,zipfile,json,urllib.request
import paramiko
DOC_URL="https://raw.githubusercontent.com/bodgybro/spr-heartbeat-publisher/8666148d174bbd5fa916ae9b9efed4d8c0bb1a43/railway/docs/paths-RC1.txt"
ZIP="SPR-Search-RC1-Bodgybros.zip"
FILES=(".htaccess","admin-api.php","admin.js","auth-api.php","index.html",
       "index.php","roster-cache-api.php","roster-relay-api.php","script.js",
       "spr-index-api.php","spr-pdf-sync.php","spr-search-logo.gif","style.css")
def sha(b):return hashlib.sha256(b).hexdigest()
def read(s,p):
    with s.open(p,"rb") as f:return f.read()
def write(s,p,b):
    with s.open(p,"wb") as f:f.write(b)
def main():
    keytext=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode()
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(keytext));break
        except Exception:pass
    if key is None:raise RuntimeError("Configured private key not readable")
    root=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
    if root.endswith("/sps/spr"):root=root[:-4]
    elif root.endswith("/public_html"):root+="/sps"
    if not root.endswith("/sps"):raise RuntimeError("Unexpected SFTP_ROOT")
    ssh=paramiko.SSHClient()
    ssh.load_host_keys("/data/credentials/spr-sftp-known_hosts")
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ["SFTP_HOST"],username=os.environ["SFTP_USERNAME"],
        port=int(os.environ.get("SFTP_PORT") or 22),pkey=key,
        look_for_keys=False,allow_agent=False,timeout=15)
    s=ssh.open_sftp()
    try:
        app={name:read(s,posixpath.join(root,name)) for name in FILES}
        if not all(t in app["script.js"] for t in
                   (b"function sprSelectionMatches(",b"function sprOriginalPdfMatchesIndex(",
                    b"async function prepareShiftPdfUrl(",b"async function loadOnlinePdf(){")):
            raise RuntimeError("Live script differs from working 687; cannot snapshot")
        for name in ("index.php","index.html"):
            old=app[name].decode()
            if 'class="build-number">Build 687' in old and "script.js?v=687" in old:
                new=old.replace('class="build-number">Build 687',
                                'class="build-number">RC1',1).replace("script.js?v=687","script.js?v=RC1",1)
            elif 'class="build-number">RC1' in old and "script.js?v=RC1" in old:
                new=old
            else:raise RuntimeError("Unrecognised live "+name+"; nothing installed")
            app[name]=new.encode()
        note=urllib.request.urlopen(DOC_URL,timeout=20).read()
        if not note.startswith(b"SPR SEARCH RC1"):raise RuntimeError("Unexpected paths.txt source")
        doc_path=posixpath.join(root,"paths.txt")
        try:existing=read(s,doc_path)
        except IOError:existing=b""
        if existing and b"SPR SEARCH RC1" not in existing:
            note=existing.rstrip()+b"\n\n"+note
        elif existing and b"SPR SEARCH RC1" in existing:
            note=existing
        app["paths.txt"]=note
        app["README-RC1.txt"]=(
            "SPR Search RC1 (working Build 687)\n"
            "ZIP is a flat snapshot of verified live application files.\n"
            "Restore files into public_html/sps. See paths.txt.\n"
            "Live SPR PDFs, indexes, rosters and credentials are excluded.\n").encode()
        app["SHA256SUMS.json"]=(json.dumps({n:sha(b) for n,b in sorted(app.items())},
                                               sort_keys=True,indent=2)+"\n").encode()
        out=io.BytesIO()
        with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED,compresslevel=8) as z:
            for name,data in sorted(app.items()):z.writestr(name,data)
        package=out.getvalue()
        with zipfile.ZipFile(io.BytesIO(package)) as z:
            if z.testzip() or set(z.namelist())!=set(app):raise RuntimeError("Bad ZIP")
            if any(z.read(n)!=data for n,data in app.items()):raise RuntimeError("ZIP data mismatch")
        changes={"index.php":app["index.php"],"index.html":app["index.html"],
                 "paths.txt":note,ZIP:package}
        original={}
        for name in changes:
            try:original[name]=read(s,posixpath.join(root,name))
            except IOError:original[name]=None
        staged=[];done=[]
        try:
            for name,data in changes.items():
                dest=posixpath.join(root,name)
                tmp=dest+".rc1-stage-"+str(os.getpid())
                write(s,tmp,data)
                if sha(read(s,tmp))!=sha(data):raise RuntimeError("Stage mismatch "+name)
                staged.append((name,tmp,dest))
            for name,tmp,dest in staged:
                s.posix_rename(tmp,dest);done.append(name)
                if sha(read(s,dest))!=sha(changes[name]):raise RuntimeError("Live mismatch "+name)
                print("[RC1 LIVE VERIFIED]",name,sha(changes[name])[:16],flush=True)
        except Exception:
            for name in reversed(done):
                dest=posixpath.join(root,name)
                if original[name] is None:
                    try:s.remove(dest)
                    except Exception:pass
                else:
                    tmp=dest+".rc1-rollback-"+str(os.getpid())
                    write(s,tmp,original[name]);s.posix_rename(tmp,dest)
                print("[RC1 ROLLBACK]",name,flush=True)
            raise
        finally:
            for name,tmp,dest in staged:
                try:s.remove(tmp)
                except Exception:pass
        print("[RC1 COMPLETE] ZIP",len(package),"bytes; files",len(app),flush=True)
    finally:s.close();ssh.close()
if __name__=="__main__":main()
