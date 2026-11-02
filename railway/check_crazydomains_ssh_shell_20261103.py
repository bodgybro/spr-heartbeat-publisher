#!/usr/bin/env python3
"""Read-only SSH shell capability test for fast Kustom SPR migration."""
import os,io,base64,paramiko
def source_key():
    blob=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode()
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:return cls.from_private_key(io.StringIO(blob))
        except Exception:pass
    raise RuntimeError("Source key not readable")
def test(label,host,user,port,key,known):
    c=paramiko.SSHClient();c.load_host_keys(known)
    c.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        c.connect(hostname=host,username=user,port=port,pkey=key,timeout=10,
                  auth_timeout=10,banner_timeout=10,allow_agent=False,look_for_keys=False)
        c.get_transport().set_keepalive(20)
        print("[KUSTOM SHELL]",label,"key authenticated",flush=True)
        for command in ("printf 'SHELL_OK\\n'","command -v tar; command -v unzip; command -v gzip"):
            try:
                stdin,stdout,stderr=c.exec_command(command,timeout=7)
                stdout.channel.settimeout(7)
                result=stdout.read(150)
                print("[KUSTOM SHELL]",label,"shell result",repr(result.decode(errors="replace")),
                      "exit",(stdout.channel.recv_exit_status() if stdout.channel.exit_status_ready() else "no-exit"),flush=True)
                stdin.close();stdout.close();stderr.close()
            except Exception as exc:
                print("[KUSTOM SHELL]",label,"exec unavailable",type(exc).__name__,str(exc)[:90],flush=True)
                break
    except Exception as exc:
        print("[KUSTOM SHELL]",label,"SSH failed",type(exc).__name__,str(exc)[:90],flush=True)
    finally:c.close()
test("Bodgybros",os.environ["SFTP_HOST"],os.environ["SFTP_USERNAME"],
     int(os.environ.get("SFTP_PORT") or 22),source_key(),"/data/credentials/spr-sftp-known_hosts")
test("Kustom","cp-wc18.per01.ds.network","kustomvi",22,
     paramiko.Ed25519Key.from_private_key_file("/data/credentials/kustom-transfer/id_ed25519"),
     "/data/credentials/kustom-transfer/known_hosts")
