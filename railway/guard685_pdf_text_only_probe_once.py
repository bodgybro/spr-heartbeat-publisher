#!/usr/bin/env python3
import sys
print("[GUARD685 ID CHECK] launched",flush=True)
try:
 import os,io,base64,posixpath,re,hashlib
 import paramiko
 from pypdf import PdfReader
 print("[GUARD685 ID CHECK] modules loaded",flush=True)
 e=os.environ
 b=base64.b64decode(e["SFTP_PRIVATE_KEY_B64"]).decode()
 k=None
 for t in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
  try:k=t.from_private_key(io.StringIO(b));break
  except Exception:pass
 if k is None:raise RuntimeError("ssh key not available")
 ssh=paramiko.SSHClient()
 ssh.load_host_keys("/data/credentials/spr-sftp-known_hosts")
 ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
 ssh.connect(hostname=e["SFTP_HOST"],port=int(e.get("SFTP_PORT") or 22),
  username=e["SFTP_USERNAME"],pkey=k,timeout=10,auth_timeout=10,banner_timeout=10,
  look_for_keys=False,allow_agent=False)
 print("[GUARD685 ID CHECK] SFTP connected",flush=True)
 root=posixpath.normpath(e["SFTP_ROOT"].replace("\\","/"))
 if root.endswith("/sps/spr/d") or root.endswith("/sps/spr/g"):root=posixpath.dirname(posixpath.dirname(posixpath.dirname(root)))
 elif root.endswith("/sps/spr"):root=posixpath.dirname(root)
 elif root.endswith("/public_html"):root=posixpath.join(root,"sps")
 with ssh.open_sftp() as f:
  f.get_channel().settimeout(35)
  for role,title in (("g","Guards"),("d","Drivers")):
   path=posixpath.join(root,"spr",role,"All "+title+" Combined 26_10_2026.pdf")
   size=f.stat(path).st_size
   print("[GUARD685 ID CHECK] reading "+role+" "+str(size)+" bytes",flush=True)
   with f.open(path,"rb") as fd:
    fd.prefetch(file_size=size,max_concurrent_requests=8)
    pdf=fd.read()
   print("[GUARD685 ID CHECK] "+role+" SHA-prefix="+hashlib.sha256(pdf).hexdigest()[:16]+" downloaded "+str(len(pdf))+" bytes",flush=True)
   reader=PdfReader(io.BytesIO(pdf),strict=False)
   print("[GUARD685 ID CHECK] role="+role+" pages="+str(len(reader.pages)),flush=True)
   for page in (0,1,20):
    if page>=len(reader.pages):continue
    content=(reader.pages[page].extract_text() or "")[:1400]
    headers=re.findall(r"Sydney\s+Trains?\s+(Driver|Guard)\b",content,re.I)
    print("[GUARD685 ID CHECK] role="+role+" page="+str(page+1)+" printed-role="+repr(headers[:3])+" driver="+str(bool(re.search(r"\bDriver\b",content,re.I)))+" guard="+str(bool(re.search(r"\bGuard\b",content,re.I))),flush=True)
 ssh.close()
except Exception as exc:
 print("[GUARD685 ID CHECK FAILED] "+type(exc).__name__+" "+str(exc)[:160],flush=True)
 sys.exit(1)
