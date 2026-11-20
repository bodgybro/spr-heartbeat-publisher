"""Idempotent one-time Kustom platform cron via authorised Railway key; no secrets or unrelated crontab contents logged."""
import pathlib, sys, paramiko
HOST="cp-wc18.per01.ds.network"
USER="kustomvi"
KEY=pathlib.Path("/data/credentials/kustom-transfer/id_ed25519")
KNOWN_HOSTS=pathlib.Path("/data/credentials/kustom-transfer/known_hosts")
SCRIPT="/home10/kustomvi/sps-private-assets/platform-auto-refresh.php"
ENTRY="7 * * * * /usr/local/bin/php "+SCRIPT+" --cron"

def remote(ssh,cmd,payload=None):
    stdin,stdout,stderr=ssh.exec_command(cmd,timeout=20)
    if payload is not None:
        stdin.write(payload)
        stdin.flush()
        stdin.channel.shutdown_write()
    out=stdout.read().decode("utf-8","replace")
    err=stderr.read().decode("utf-8","replace")
    return stdout.channel.recv_exit_status(),out,err

def main():
    if not KEY.is_file() or not KNOWN_HOSTS.is_file():
        print("KUSTOM_PLATFORM_CRON_BLOCKED credentials not present",flush=True)
        return 1
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(KNOWN_HOSTS))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=HOST,username=USER,port=22,
            pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY)),
            look_for_keys=False,allow_agent=False,timeout=18,auth_timeout=18,banner_timeout=18)
        status,_,_=remote(ssh,"test -f "+SCRIPT)
        if status!=0:
            print("KUSTOM_PLATFORM_CRON_BLOCKED private timetable PHP missing",flush=True)
            return 2
        status,_,_=remote(ssh,"command -v crontab")
        if status!=0:
            print("KUSTOM_PLATFORM_CRON_BLOCKED crontab command unavailable",flush=True)
            return 2
        status,current,stderr=remote(ssh,"crontab -l")
        if status!=0:
            if status==1 and ("no crontab for" in stderr.lower() or not stderr.strip()) and not current.strip():
                current=""
            else:
                print("KUSTOM_PLATFORM_CRON_BLOCKED unable to read crontab",flush=True)
                return 2
        existing=[line.strip() for line in current.splitlines() if "platform-auto-refresh.php" in line and not line.lstrip().startswith("#")]
        if existing:
            if existing==[ENTRY]:
                print("KUSTOM_PLATFORM_CRON_ALREADY_INSTALLED schedule verified",flush=True)
                return 0
            print("KUSTOM_PLATFORM_CRON_NOT_CHANGED existing entry needs review",flush=True)
            return 2
        updated=current.rstrip("\n")+("\n" if current.strip() else "")+ENTRY+"\n"
        status,_,_=remote(ssh,"crontab -",updated)
        if status!=0:
            print("KUSTOM_PLATFORM_CRON_BLOCKED crontab write rejected",flush=True)
            return 2
        status,verified,_=remote(ssh,"crontab -l")
        count=sum(line.strip()==ENTRY for line in verified.splitlines())
        if status!=0 or count!=1:
            print("KUSTOM_PLATFORM_CRON_ERROR post-install verification failed",flush=True)
            return 2
        print("KUSTOM_PLATFORM_CRON_INSTALLED_AND_VERIFIED schedule=7_*_*_*_*",flush=True)
        return 0
    except (paramiko.SSHException,OSError,EOFError) as exc:
        print("KUSTOM_PLATFORM_CRON_CONNECTION_ERROR "+type(exc).__name__,flush=True)
        return 3
    finally:
        ssh.close()

if __name__=="__main__":
    sys.exit(main())
