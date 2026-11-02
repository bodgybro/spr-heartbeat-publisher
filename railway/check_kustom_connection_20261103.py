#!/usr/bin/env python3
"""Read-only SFTP connection check for authorized Kustom site migration."""
import os
import stat
import paramiko

host="cp-wc18.per01.ds.network"
user="kustomvi"
port=22
keyfile="/data/credentials/kustom-transfer/id_ed25519"

client=paramiko.SSHClient()
host_file="/data/credentials/kustom-transfer/known_hosts"
os.makedirs(os.path.dirname(host_file),exist_ok=True)
client.load_host_keys(host_file) if os.path.isfile(host_file) else None
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    key=paramiko.Ed25519Key.from_private_key_file(keyfile)
    client.connect(hostname=host,port=port,username=user,pkey=key,
                   allow_agent=False,look_for_keys=False,
                   timeout=10,auth_timeout=10,banner_timeout=10)
    client.save_host_keys(host_file)
    with client.open_sftp() as sftp:
        print("[KUSTOM CONNECT] authenticated: yes",flush=True)
        home=sftp.normalize(".")
        print("[KUSTOM CONNECT] home path correct:",home.rstrip("/")=="/home10/kustomvi",flush=True)
        for path in ("/home10/kustomvi/public_html","/home10/kustomvi/public_html/sps"):
            try:
                info=sftp.stat(path)
                entries=sftp.listdir_attr(path) if stat.S_ISDIR(info.st_mode) else []
                print("[KUSTOM CONNECT] directory:",path.split("/")[-1],"exists:",stat.S_ISDIR(info.st_mode),"entry count:",len(entries),flush=True)
                print("[KUSTOM CONNECT] contains existing app:",any(item.filename in ("index.php","script.js") for item in entries),flush=True)
            except OSError as exc:
                print("[KUSTOM CONNECT] directory check unavailable:",path.split("/")[-1],type(exc).__name__,flush=True)
except (paramiko.AuthenticationException,paramiko.SSHException,OSError) as exc:
    print("[KUSTOM CONNECT] connection failed:",type(exc).__name__,str(exc)[:100],flush=True)
finally:
    client.close()
print("[KUSTOM CONNECT] check completed; no website files modified",flush=True)
