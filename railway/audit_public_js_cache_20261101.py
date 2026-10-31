#!/usr/bin/env python3
"""Read-only: compare public served scripts/HTML with SFTP versions for SPR Search."""
import base64,io,hashlib,os,posixpath,re
import requests,paramiko
e=os.environ; root=e["SFTP_ROOT"].replace("\\","/").rstrip("/")
if root.endswith("/sps/spr"):root=root[:-4]
elif root.endswith("/sps"):pass
elif root.endswith("/public_html") or root=="public_html":root+="/sps"
else:raise RuntimeError("Unexpected root")
raw=base64.b64decode(e["SFTP_PRIVATE_KEY_B64"]).decode("utf-8")
key=None
for c in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=c.from_private_key(io.StringIO(raw));break
    except Exception:pass
if key is None:raise RuntimeError("SFTP key unavailable")
ssh=paramiko.SSHClient();ssh.load_host_keys("/data/credentials/spr-sftp-known_hosts")
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=e["SFTP_HOST"],username=e["SFTP_USERNAME"],pkey=key,port=int(e.get("SFTP_PORT") or 22),allow_agent=False,look_for_keys=False,timeout=12)
ftp=ssh.open_sftp()
try:
    for f in ("script.js","index.php","index.html"):
        with ftp.open(posixpath.join(root,f),"rb") as h:data=h.read()
        print("[CACHE AUDIT SFTP]",f,len(data),hashlib.sha256(data).hexdigest()[:32],flush=True)
        if f.endswith("html") or f.endswith("php"):
            txt=data.decode("utf-8","ignore")
            for m in re.finditer(r".{0,80}script\.js.{0,150}",txt,re.I):
                print("[CACHE AUDIT IMPORT]",f,repr(m.group())[:330],flush=True)
            for token in ("serviceWorker","navigator.serviceWorker","cache-control","no-store"):
                print("[CACHE AUDIT SHELL TOKEN]",f,token,txt.lower().count(token.lower()),flush=True)
finally:
    ftp.close();ssh.close()
urls=[
    "https://www.bodgybros.com/sps/script.js?v=700-run-origin-verified-20261101-v2",
    "https://www.bodgybros.com/sps/script.js?v=700-run-origin-verified-20261101-v2&test=20261101-x",
    "https://www.bodgybros.com/sps/script.js?v=700-run-origin-verified-20261101-v1",
    "https://www.bodgybros.com/sps/?_spr_audit=20261101-578b",
]
for uri in urls:
    try:
        result=requests.get(uri,timeout=18,headers={"User-Agent":"Mozilla/5.0","Cache-Control":"no-cache","Pragma":"no-cache"})
        raw=result.content
        print("[CACHE AUDIT HTTP]",uri.split("/")[-1][:80],
              "status",result.status_code,"bytes",len(raw),"sha",hashlib.sha256(raw).hexdigest()[:32],
              "cache-control",result.headers.get("cache-control",""),
              "cf-cache-status",result.headers.get("cf-cache-status",""),
              "content-type",result.headers.get("content-type",""),flush=True)
        if result.status_code==200:
            text=raw.decode("utf-8","ignore")
            print("[CACHE AUDIT MARKERS] sort", "SPR_SORT_RUN_START_20261101" in text,
                  "originV2","SPR_568B_578B_ORIGIN_CONDITION_V2" in text,
                  "scriptRefs",re.findall(r"script\.js\?v=[A-Za-z0-9_.-]+",text)[:5],flush=True)
    except Exception as ex:
        print("[CACHE AUDIT HTTP FAILED]",uri.split("/")[-1][:40],type(ex).__name__,str(ex)[:100],flush=True)
