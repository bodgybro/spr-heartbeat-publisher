#!/usr/bin/env python3
"""Enable public Kustom apex/www AutoSSL and request HTTPS certificate.

User authorized transfer to this site. Scope is ONLY the two public hostnames
that currently lack a valid SSL certificate, never disable TLS or change DNS.
Reuses separately authorized Kustom account SSH key. cPanel UAPI used for
adding these two hostnames into AutoSSL and running its supported check.
"""
import os,ssl,socket,time,json,re,paramiko
from cryptography import x509
PUBLIC=("kustomvinyls.com","www.kustomvinyls.com")
def say(*a):print("[KUSTOM SSL REPAIR]",*a,flush=True)
ssh=paramiko.SSHClient()
ssh.load_host_keys("/data/credentials/kustom-transfer/known_hosts")
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname="cp-wc18.per01.ds.network",username="kustomvi",port=22,
    pkey=paramiko.Ed25519Key.from_private_key_file("/data/credentials/kustom-transfer/id_ed25519"),
    timeout=15,allow_agent=False,look_for_keys=False)
def uapi(fn,params=""):
    cmd="uapi --output=json SSL "+fn+(" "+params if params else "")
    stdin,stdout,stderr=ssh.exec_command(cmd,timeout=30)
    stdout.channel.settimeout(40)
    output=stdout.read(180000).decode(errors="replace")
    errors=stderr.read(700).decode(errors="replace")
    code=stdout.channel.recv_exit_status() if stdout.channel.exit_status_ready() else -1
    try:d=json.loads(output).get("result") or {}
    except Exception as ex:
        say("UAPI",fn,"parse error",type(ex).__name__,"status",code)
        return None
    say("UAPI",fn,"ok",d.get("status"),"exit",code,"errors",str(d.get("errors") or [])[:240])
    return d
def names_for(host):
    ctx=ssl._create_unverified_context()
    with socket.create_connection((host,443),timeout=9) as sock:
        with ctx.wrap_socket(sock,server_hostname=host) as tls:
            cert=x509.load_der_x509_certificate(tls.getpeercert(binary_form=True))
            try:return cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
            except x509.ExtensionNotFound:return []
def covered(names):
    return all(any(n==d or (n.startswith("*.") and d.endswith(n[1:])) for n in names) for d in PUBLIC)
try:
    current=names_for(PUBLIC[1])
    if covered(current):
        say("Certificate already covers apex/www. No change.")
    else:
        excluded=uapi("get_autossl_excluded_domains")
        if excluded is None:raise RuntimeError("Cannot safely read current AutoSSL exclusions")
        text=str(excluded.get("data") or "").lower()
        exclusions=set(re.findall(r"(?:[a-z0-9_-]+\.)*kustomvinyls\.com",text))
        targeted=sorted(set(PUBLIC)&exclusions)
        say("Public hostnames currently excluded",targeted)
        if targeted:
            removed=uapi("remove_autossl_excluded_domains","domains="+",".join(targeted))
            if not removed or removed.get("status")!=1:
                raise RuntimeError("Couldn't include Kustom public hostnames in AutoSSL")
            say("Enabled AutoSSL for public Kustom hostnames only",targeted)
        still=uapi("get_autossl_excluded_domains")
        names=set(re.findall(r"(?:[a-z0-9_-]+\.)*kustomvinyls\.com",
                             str((still or {}).get("data") or "").lower()))
        if set(PUBLIC)&names:
            raise RuntimeError("Public hostnames remain excluded; no further action")
        inprogress=uapi("is_autossl_check_in_progress")
        # The current account's AutoSSL check is safely idempotent.
        result=uapi("start_autossl_check")
        if not result or result.get("status")!=1:
            raise RuntimeError("AutoSSL check request was denied")
        say("Standard cPanel AutoSSL certificate check started")
        for idx in range(10):
            time.sleep(12)
            try:
                now=names_for(PUBLIC[1])
                ok=covered(now)
                say("TLS poll",idx+1,"public SAN valid",ok,
                    "names",now[:9])
                if ok:
                    say("HTTPS CERTIFICATE READY",PUBLIC)
                    break
            except Exception as ex:
                say("TLS poll",idx+1,"failed",type(ex).__name__)
        else:
            say("Certificate not issued yet. May require hosting AutoSSL validation or processing.")
            probs=uapi("get_autossl_problems")
            data=(probs or {}).get("data")
            if data:say("AutoSSL reported problem summary",str(data)[:850])
finally:
    ssh.close()
