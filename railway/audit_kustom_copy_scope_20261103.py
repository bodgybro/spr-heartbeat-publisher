#!/usr/bin/env python3
"""Read-only scope, quotas, and hardcoded-host audit for Kustom migration."""
import os,io,base64,posixpath,stat,collections,re
import paramiko

SOURCE_USER=os.environ["SFTP_USERNAME"]
SOURCE_HOST=os.environ["SFTP_HOST"]
RAW=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode()
SOURCE_ROOT=os.environ["SFTP_ROOT"].rstrip("/")
if SOURCE_ROOT.endswith("/sps/spr"):SOURCE_ROOT=SOURCE_ROOT[:-4]
elif SOURCE_ROOT.endswith("/public_html"):SOURCE_ROOT+="/sps"
if not SOURCE_ROOT.endswith("/sps"):raise RuntimeError("Unexpected source root")
DEST_ROOT="/home10/kustomvi/public_html/sps"
def make_client(host,user,key,knownhosts,port):
    cli=paramiko.SSHClient()
    cli.load_host_keys(knownhosts)
    cli.set_missing_host_key_policy(paramiko.RejectPolicy())
    cli.connect(hostname=host,username=user,port=port,pkey=key,timeout=12,auth_timeout=12,
                banner_timeout=12,look_for_keys=False,allow_agent=False)
    return cli
key=None
for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=cls.from_private_key(io.StringIO(RAW));break
    except Exception:pass
if key is None:raise RuntimeError("Source SSH private key inaccessible")
src=make_client(SOURCE_HOST,SOURCE_USER,key,"/data/credentials/spr-sftp-known_hosts",int(os.environ.get("SFTP_PORT") or 22))
dest=make_client("cp-wc18.per01.ds.network","kustomvi",
                 paramiko.Ed25519Key.from_private_key_file("/data/credentials/kustom-transfer/id_ed25519"),
                 "/data/credentials/kustom-transfer/known_hosts",22)
try:
  with src.open_sftp() as fs,dest.open_sftp() as fd:
    files=[]
    tree=[("",SOURCE_ROOT)]
    categories=collections.defaultdict(lambda:[0,0])
    exts=collections.defaultdict(lambda:[0,0])
    samples={}
    while tree:
      rel,parent=tree.pop()
      for a in fs.listdir_attr(parent):
        name=a.filename
        if name in (".",".."):continue
        relative=posixpath.join(rel,name) if rel else name
        if stat.S_ISLNK(a.st_mode):continue
        if stat.S_ISDIR(a.st_mode):
            tree.append((relative,posixpath.join(parent,name)))
            continue
        if not stat.S_ISREG(a.st_mode):continue
        size=a.st_size
        files.append((relative,size))
        first=relative.split("/")[0] if "/" in relative else "(root)"
        categories[first][0]+=1
        categories[first][1]+=size
        ext=posixpath.splitext(relative)[1].lower()
        exts[ext][0]+=1
        exts[ext][1]+=size
        if first=="(root)" and (ext in (".php",".html",".js",".json",".txt",".htaccess",".css") or name==".htaccess") and size<2000000:
            with fs.open(posixpath.join(SOURCE_ROOT,relative),"rb") as f:
                b=f.read()
            counts=collections.Counter()
            for domain in ("www.bodgybros.com","bodgybros.com","www.kustomvinyls.com","kustomvinyls.com","spr-heartbeat-publisher"):
                counts[domain]=b.lower().count(domain.encode())
            samples[name]=dict(counts)
    print("[KUSTOM SCOPE] TOTAL_FILES",len(files),"TOTAL_BYTES",sum(n for _,n in files),flush=True)
    for cat,(n,b) in sorted(categories.items()):
        print("[KUSTOM SCOPE] FOLDER",cat,"FILES",n,"BYTES",b,flush=True)
    for ext,(n,b) in sorted(exts.items(),key=lambda x:x[1][1],reverse=True)[:10]:
        print("[KUSTOM SCOPE] EXT",ext,"FILES",n,"BYTES",b,flush=True)
    for name,counts in samples.items():
        if any(counts.values()):
            print("[KUSTOM SCOPE] HARDCODED",name,counts,flush=True)
    try:
        st=fd.statvfs("/home10/kustomvi/public_html")
        print("[KUSTOM SCOPE] DEST_AVAILABLE_BYTES",st.f_bavail*st.f_frsize,flush=True)
    except Exception as exc:
        print("[KUSTOM SCOPE] DEST_SPACE_CHECK_FAILED",type(exc).__name__,flush=True)
    try:
        data=fd.listdir_attr(DEST_ROOT)
        print("[KUSTOM SCOPE] DEST_EXISTING_SPS yes","ENTRIES",len(data),flush=True)
    except FileNotFoundError:
        print("[KUSTOM SCOPE] DEST_EXISTING_SPS no",flush=True)
    print("[KUSTOM SCOPE] LARGEST_FILES",[(a,b) for a,b in sorted(files,key=lambda x:x[1],reverse=True)[:12]],flush=True)
finally:
    src.close();dest.close()
