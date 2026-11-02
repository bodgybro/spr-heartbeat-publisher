#!/usr/bin/env python3
"""Read-only Kustom DNS, TLS certificate, HTTP and copied site verification."""
import ssl,socket,datetime,requests,urllib3,hashlib
from cryptography import x509
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
def say(*a):print("[KUSTOM PUBLIC]",*a,flush=True)
for host in ("kustomvinyls.com","www.kustomvinyls.com"):
    try:
        ips=sorted(set(t[4][0] for t in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)))
        say(host,"DNS resolved",ips,"includes hosting address", "203.170.86.65" in ips)
    except Exception as ex:
        say(host,"DNS resolution error",type(ex).__name__,str(ex)[:100])
    for proto in ("http","https"):
        url=f"{proto}://{host}/sps/"
        for verified in ([True,False] if proto=="https" else [True]):
            try:
                r=requests.get(url,timeout=15,allow_redirects=False,verify=verified)
                say(url,"TLS verified",verified,"status",r.status_code,
                    "redirect host",requests.utils.urlparse(r.headers.get("Location","")).hostname or "none",
                    "Build700",("Build 700" in r.text),"bytes",len(r.content),
                    "server",(r.headers.get("Server") or "")[:60])
            except Exception as ex:
                say(url,"TLS verified",verified,"failed",type(ex).__name__,str(ex)[:180])
    try:
        ctx=ssl._create_unverified_context()
        with socket.create_connection((host,443),timeout=10) as sock:
            with ctx.wrap_socket(sock,server_hostname=host) as tls:
                raw=tls.getpeercert(binary_form=True)
                cert=x509.load_der_x509_certificate(raw)
                san=cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
                say(host,"CERT subject",str(cert.subject.rfc4514_string())[:160],"issuer",str(cert.issuer.rfc4514_string())[:100],
                    "not_after_utc",str(cert.not_valid_after_utc),
                    "SAN",san[:15],"SHA",hashlib.sha256(raw).hexdigest()[:14])
    except Exception as ex:
        say(host,"certificate read error",type(ex).__name__,str(ex)[:110])
try:
    r=requests.get("http://203.170.86.65/sps/",headers={"Host":"www.kustomvinyls.com"},
                   timeout=12,allow_redirects=False)
    say("IP direct hosted route","status",r.status_code,"Build700",("Build 700" in r.text),
        "redirect",str(r.headers.get("Location",""))[:120])
except Exception as ex:
    say("IP direct check failed",type(ex).__name__,str(ex)[:100])
say("Read only check complete",flush=True)
