#!/usr/bin/env python3
"""Precisely inspect only specific roster search and crew row extraction in live JS."""
import os,io,base64,paramiko,posixpath
kraw=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode()
key=None
for t in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=t.from_private_key(io.StringIO(kraw));break
    except Exception:pass
c=paramiko.SSHClient()
c.load_host_keys("/data/credentials/spr-sftp-known_hosts")
c.set_missing_host_key_policy(paramiko.RejectPolicy())
c.connect(hostname=os.environ["SFTP_HOST"],username=os.environ["SFTP_USERNAME"],
 port=int(os.environ.get("SFTP_PORT") or 22),pkey=key,timeout=12,
 allow_agent=False,look_for_keys=False)
root=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
if root.endswith("/sps/spr"):root=root[:-4]
elif root.endswith("/public_html"):root+="/sps"
try:
 with c.open_sftp() as s:
    with s.open(posixpath.join(root,"script-700-fromto-locations-v1.js"),"rb") as f:
        f.prefetch(max_concurrent_requests=32)
        lines=f.read().decode("utf8","replace").splitlines()
 for begin,end in ((623,673),(784,847),(899,948),(1169,1246),
                   (1518,1550),(2410,2526),(2603,2686)):
    print("[FOCUS SRC BLOCK]",begin,end,flush=True)
    for j in range(begin-1,min(end,len(lines))):
        print("[FOCUS SRC] "+str(j+1)+" "+lines[j],flush=True)
finally:c.close()
