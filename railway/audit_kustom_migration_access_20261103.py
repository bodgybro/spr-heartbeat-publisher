#!/usr/bin/env python3
"""READ ONLY destination access audit for SPR Search migration to Kustom Vinyls.
No site writes, no DNS changes, no secret values in logs.
"""
import os,io,base64,posixpath,stat
import requests,paramiko,urllib.parse

def safe_bool(b):return "yes" if b else "no"
e=os.environ
print("[KUSTOM MIGRATION] BEGIN",flush=True)
print("[KUSTOM MIGRATION] separate Kustom SFTP credentials configured:",
      safe_bool(all(e.get(x) for x in ("KUSTOM_SFTP_HOST","KUSTOM_SFTP_USERNAME","KUSTOM_SFTP_PRIVATE_KEY_B64","KUSTOM_SFTP_ROOT"))),flush=True)
print("[KUSTOM MIGRATION] cPanel API configured:",
      safe_bool(all(e.get(x) for x in ("CPANEL_HOST","CPANEL_USERNAME","CPANEL_API_TOKEN"))),flush=True)
print("[KUSTOM MIGRATION] cPanel hostname mentions Kustom:",
      safe_bool("kustomvinyls" in e.get("CPANEL_HOST","").lower()),flush=True)
print("[KUSTOM MIGRATION] primary SFTP host mentions Kustom:",
      safe_bool("kustomvinyls" in e.get("SFTP_HOST","").lower()),flush=True)
print("[KUSTOM MIGRATION] separate Kustom known-hosts file:",
      safe_bool(os.path.isfile("/data/credentials/kustom-sftp-known-hosts")),flush=True)

# Query only the authenticated hosting account's domain membership.
if all(e.get(x) for x in ("CPANEL_HOST","CPANEL_USERNAME","CPANEL_API_TOKEN")):
    raw=e["CPANEL_HOST"].strip()
    host=urllib.parse.urlparse(raw if "://" in raw else "https://"+raw).hostname
    port=int(e.get("CPANEL_PORT") or 2083)
    try:
        r=requests.get(f"https://{host}:{port}/execute/DomainInfo/list_domains",
          headers={"Authorization":f"cpanel {e['CPANEL_USERNAME']}:{e['CPANEL_API_TOKEN']}"},
          timeout=12,verify=str(e.get("CPANEL_VERIFY_SSL","1")).lower() not in ("0","no","false"))
        obj=r.json() if r.status_code==200 else {}
        data=obj.get("data") or {}
        kinds=("main_domain","addon_domains","parked_domains","sub_domains")
        available=[(k,data.get(k)) for k in kinds]
        present=any("kustomvinyls.com" in str(v).lower() for _,v in available)
        print("[KUSTOM MIGRATION] cPanel UAPI status:",r.status_code,
              "account-authorized:",safe_bool(obj.get("status")==1),
              "Kustom domain listed:",safe_bool(present),flush=True)
        print("[KUSTOM MIGRATION] cPanel main domain is bodgybros:",
              safe_bool("bodgybros.com" in str(data.get("main_domain","")).lower()),flush=True)
    except Exception as exc:
        print("[KUSTOM MIGRATION] cPanel domain check failed:",type(exc).__name__,flush=True)

# SFTP primary account: check whether Kustom's root is inside the same
# authenticated hosting account without touching any files.
try:
    private=base64.b64decode(e["SFTP_PRIVATE_KEY_B64"]).decode("utf-8")
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(private));break
        except Exception:pass
    if key is None:raise RuntimeError("Configured key not parseable")
    ssh=paramiko.SSHClient()
    ssh.load_host_keys("/data/credentials/spr-sftp-known_hosts")
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=e["SFTP_HOST"],username=e["SFTP_USERNAME"],
      port=int(e.get("SFTP_PORT") or 22),pkey=key,timeout=10,
      auth_timeout=10,banner_timeout=10,allow_agent=False,look_for_keys=False)
    with ssh.open_sftp() as ftp:
        root=e["SFTP_ROOT"].replace("\\","/").rstrip("/")
        if root.endswith("/sps/spr"):root=root[:-4]
        elif root.endswith("/public_html"):root+="/sps"
        if not root.endswith("/sps"):raise RuntimeError("Source not under /sps")
        entries=ftp.listdir_attr(root)
        app=[x for x in entries if stat.S_ISREG(x.st_mode)]
        pdf_dirs=[x for x in entries if stat.S_ISDIR(x.st_mode) and x.filename in ("spr","rosters","roster","cache")]
        print("[KUSTOM MIGRATION] source SFTP reachable: yes, application files:",
              len(app),"special dirs:",len(pdf_dirs),flush=True)
        for candidate in (
            posixpath.normpath(posixpath.join(root,"..","..","kustomvinyls.com")),
            posixpath.normpath(posixpath.join(root,"..","..","kustomvinyls")),
            posixpath.normpath(posixpath.join(root,"..","kustomvinyls.com")),
            posixpath.normpath(posixpath.join(root,"..","..","public_html","kustomvinyls.com"))
        ):
            try:
                st=ftp.stat(candidate)
                if stat.S_ISDIR(st.st_mode):
                    print("[KUSTOM MIGRATION] possible Kustom directory in same SFTP account: yes (requires verification)",flush=True)
                    break
            except Exception:pass
        else:
            print("[KUSTOM MIGRATION] possible Kustom directory in same SFTP account: not found",flush=True)
    ssh.close()
except Exception as exc:
    print("[KUSTOM MIGRATION] source SFTP check failed:",type(exc).__name__,str(exc)[:140],flush=True)

# Public DNS evidence, no changes.
for d in ("bodgybros.com","www.bodgybros.com","kustomvinyls.com","www.kustomvinyls.com"):
    try:
        r=requests.get("https://dns.google/resolve",params={"name":d,"type":"A"},timeout=8)
        data=r.json()
        answers=data.get("Answer") or []
        print("[KUSTOM MIGRATION DNS]",d,"rcode",data.get("Status"),"A records",
              len([a for a in answers if a.get("type")==1]),flush=True)
    except Exception as ex:
        print("[KUSTOM MIGRATION DNS]",d,"unavailable",type(ex).__name__,flush=True)
print("[KUSTOM MIGRATION] END",flush=True)
