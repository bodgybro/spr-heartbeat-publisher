#!/usr/bin/env python3
"""Read-only inspection of live Bodgybros run-search ordering, no website edits."""
import os,io,base64,posixpath,hashlib,re
import paramiko
e=os.environ
root=e["SFTP_ROOT"].replace("\\","/").rstrip("/")
if root.endswith("/sps/spr"):root=root[:-4]
elif root.endswith("/sps"):pass
elif root.endswith("/public_html") or root=="public_html":root+="/sps"
else:raise RuntimeError("Unexpected SFTP root")
raw=base64.b64decode(e["SFTP_PRIVATE_KEY_B64"]).decode("utf-8")
key=None
for kind in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=kind.from_private_key(io.StringIO(raw));break
    except Exception:pass
if key is None:raise RuntimeError("Existing SFTP key unavailable")
ssh=paramiko.SSHClient()
ssh.load_host_keys("/data/credentials/spr-sftp-known_hosts")
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
try:
    ssh.connect(hostname=e["SFTP_HOST"],username=e["SFTP_USERNAME"],port=int(e.get("SFTP_PORT") or 22),
                pkey=key,look_for_keys=False,allow_agent=False,timeout=12,auth_timeout=12,banner_timeout=12)
    with ssh.open_sftp() as sftp:
        for name in ("script.js","index.php","index.html"):
            with sftp.open(posixpath.join(root,name),"rb") as inp:buf=inp.read()
            print("[RUN ORDER INSPECT SHA]",name,hashlib.sha256(buf).hexdigest()[:32],len(buf),flush=True)
            if name!="script.js":continue
            js=buf.decode("utf-8")
            for token in ("function searchRun(value){","function recordTime(record){",
                          "function chronologicalRecordAnchor(records){",
                          "function chronologicalRecordValue(record,anchor){",
                          "function minutesFromTime("):
                count=js.count(token);ix=js.find(token)
                print("[RUN ORDER INSPECT MARKER]",token,"count",count,flush=True)
                if ix>=0:print("[RUN ORDER INSPECT CODE]",token,repr(js[ix:ix+1700]),flush=True)
            for token in ("runStartTime","incomingRelieveTime","originTiming","function renderCard(r){"):
                print("[RUN ORDER INSPECT FIELD]",token,"occurrences",js.count(token),flush=True)
except Exception as exc:
    print("[RUN ORDER INSPECT FAILED]",type(exc).__name__,str(exc)[:170],flush=True)
    raise
finally:ssh.close()
