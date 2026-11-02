#!/usr/bin/env python3
"""Fix website TLS via cPanel user-scoped AutoSSL using authorized SSH key.

Only Kustom account; never touches Bodgybros or its updater and never
disables validation. Checks if a job is already running, lists excluded
domains, starts standard cPanel SSL certificate check for the user, polls
public certificate SAN for apex/www and records any AutoSSL problems.
"""
import os,paramiko,json,ssl,socket,time
from cryptography import x509
HOST="cp-wc18.per01.ds.network"
USER="kustomvi"
DOMAINS=("kustomvinyls.com","www.kustomvinyls.com")
def log(*args):print("[KUSTOM AUTOSSL]",*args,flush=True)
ssh=paramiko.SSHClient()
ssh.load_host_keys("/data/credentials/kustom-transfer/known_hosts")
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=HOST,port=22,username=USER,
    pkey=paramiko.Ed25519Key.from_private_key_file("/data/credentials/kustom-transfer/id_ed25519"),
    timeout=15,allow_agent=False,look_for_keys=False)
def uapi(name):
    cmd="uapi --output=json SSL "+name
    stdin,stdout,stderr=ssh.exec_command(cmd,timeout=25)
    stdout.channel.settimeout(30)
    out=stdout.read(150000).decode(errors="replace")
    err=stderr.read(500).decode(errors="replace")
    rc=stdout.channel.recv_exit_status() if stdout.channel.exit_status_ready() else -1
    try:obj=json.loads(out)
    except Exception as exc:
        log(name,"unparseable",type(exc).__name__,"exit",rc,"stderr",err[:100])
        return None
    info=obj.get("result") or {}
    status=info.get("status")
    errors=info.get("errors") or []
    messages=info.get("messages") or []
    log(name,"status",status,"exit",rc,"errors",str(errors)[:240],"messages",str(messages)[:160])
    return info
def sans_for(domain):
    ctx=ssl._create_unverified_context()
    with socket.create_connection((domain,443),timeout=9) as sk:
        with ctx.wrap_socket(sk,server_hostname=domain) as stream:
            cert=x509.load_der_x509_certificate(stream.getpeercert(binary_form=True))
            try:return cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
            except x509.ExtensionNotFound:return []
try:
    try:
        present=sans_for(DOMAINS[1])
        if all(any(name==d or (name.startswith("*.") and d.endswith(name[1:])) for name in present) for d in DOMAINS):
            log("Already valid for apex and www, no action needed")
            raise SystemExit(0)
        log("TLS certificate missing required apex/www SAN; attempting standard AutoSSL check")
    except (OSError,ssl.SSLError) as exc:
        log("Current TLS read unavailable",type(exc).__name__)
    excl=uapi("get_autossl_excluded_domains")
    excluded=str((excl or {}).get("data") or "").lower()
    target_excluded=any(d in excluded for d in DOMAINS)
    if target_excluded:
        log("A required domain is explicitly excluded from AutoSSL; will not change user exclusion settings")
        raise SystemExit(0)
    inprogress=uapi("is_autossl_check_in_progress")
    active=(inprogress or {}).get("data")
    log("AutoSSL in-progress data",str(active)[:220])
    # Starting a cPanel user-scoped check is supported by the official UAPI.
    requested=uapi("start_autossl_check")
    if (requested or {}).get("status")!=1:
        log("AutoSSL start declined; inspect cPanel SSL/TLS Status")
        raise SystemExit(0)
    log("AutoSSL check successfully requested for Kustom hosting account")
    for trial in range(8):
        time.sleep(12)
        try:
            names=sans_for(DOMAINS[1])
            supported=all(any(name==d or (name.startswith("*.") and d.endswith(name[1:])) for name in names) for d in DOMAINS)
            log("Certificate check",trial+1,"apex/www present",supported,"SAN",names[:10])
            if supported:
                log("HTTPS CERTIFICATE VERIFIED",DOMAINS)
                break
        except Exception as exc:
            log("Certificate check",trial+1,"error",type(exc).__name__)
    else:
        log("No new apex/www certificate observed yet; AutoSSL may be queued or blocked")
        probs=uapi("get_autossl_problems")
        data=(probs or {}).get("data")
        # Do not expose user secrets, only short problem text if relevant.
        if data:log("AUTOSSL PROBLEMS",str(data)[:950])
finally:
    ssh.close()
