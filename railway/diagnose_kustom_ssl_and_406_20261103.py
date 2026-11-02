#!/usr/bin/env python3
"""Read-only Kustom domain SSL, HTTP 406, cPanel status and PHP files audit."""
import ssl,socket,requests,urllib3,hashlib,os,paramiko,json,re,stat
from cryptography import x509
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
def say(*args):print("[KUSTOM HOST CHECK]",*args,flush=True)
host="www.kustomvinyls.com"
ua="Mozilla/5.0 (iPhone; CPU iPhone OS 26_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/153.0.0 Mobile/15E148 Safari/604.1"
headers={"User-Agent":ua,"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8","Accept-Language":"en-AU,en;q=0.9"}
for domain in ("kustomvinyls.com","www.kustomvinyls.com"):
 for path in ("/","/sps/","/sps/index.html","/sps/style.css","/robots.txt"):
  url=f"https://{domain}{path}"
  try:
   r=requests.get(url,headers=headers,verify=False,timeout=13,allow_redirects=False)
   say("HTTP",domain,path,r.status_code,"len",len(r.content),"Build700",("Build 700" in r.text),
       "body_signature",re.sub(r"\s+"," ",r.text[:170])[:150] if len(r.content)<400 else "[long]",
       "server",r.headers.get("Server","")[:50])
  except Exception as ex:say("HTTP",domain,path,type(ex).__name__,str(ex)[:100])
 try:
  ctx=ssl._create_unverified_context()
  with socket.create_connection((domain,443),timeout=10) as sock:
   with ctx.wrap_socket(sock,server_hostname=domain) as tls:
    cert=x509.load_der_x509_certificate(tls.getpeercert(binary_form=True))
    sans=[]
    try:sans=cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:pass
    say("CERT",domain,"subject",cert.subject.rfc4514_string()[:110],
        "issuer",cert.issuer.rfc4514_string()[:110],
        "valid_through",str(cert.not_valid_after),
        "SAN",sans[:12],
        "SHA",hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()[:20])
 except Exception as ex:say("CERT",domain,"error",type(ex).__name__,str(ex)[:110])
ssh=paramiko.SSHClient()
ssh.load_host_keys("/data/credentials/kustom-transfer/known_hosts")
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname="cp-wc18.per01.ds.network",username="kustomvi",port=22,
 pkey=paramiko.Ed25519Key.from_private_key_file("/data/credentials/kustom-transfer/id_ed25519"),
 timeout=12,allow_agent=False,look_for_keys=False)
try:
 with ssh.open_sftp() as ftp:
  root="/home10/kustomvi/public_html/sps"
  for name in ("index.php","index.html","script.js","script-700-fromto-locations-v1.js",".htaccess"):
   try:
    item=ftp.stat(root+"/"+name)
    with ftp.open(root+"/"+name,"rb") as f:
     b=f.read(min(item.st_size,800000))
    say("FILE",name,"bytes",item.st_size,"Build700",b"Build 700" in b,
        "versioned JS",b"script-700-fromto-locations-v1.js" in b,
        "host redirect",b"https://www.bodgybros.com/sps" in b)
   except Exception as ex:say("FILE",name,"error",type(ex).__name__)
 for cmdname,cmd in (
   ("php-cli","command -v php && php -l /home10/kustomvi/public_html/sps/index.php"),
   ("cpanel-uapi","command -v uapi"),
   ("modsec","uapi --output=json ModSecurity list_domains"),
   ("ssl-install","uapi --output=json SSL installed_hosts"),
 ):
  try:
   stdin,stdout,stderr=ssh.exec_command(cmd,timeout=12)
   stdout.channel.settimeout(15)
   out=stdout.read(350000).decode(errors="replace")
   err=stderr.read(700).decode(errors="replace")
   status=stdout.channel.recv_exit_status() if stdout.channel.exit_status_ready() else "no exit"
   if cmdname in ("ssl-install","modsec"):
    try:
     obj=json.loads(out)
     data=(obj.get("result") or {}).get("data")
     text=json.dumps(data,default=str)
     if cmdname=="ssl-install":
      domains=set(re.findall(r"[A-Za-z0-9.-]*kustomvinyls\.com",text))
      say("UAPI",cmdname,"exit",status,"status",(obj.get("result") or {}).get("status"),
          "domains",sorted(domains)[:8],"data_keys",list(data)[:10] if isinstance(data,dict) else "list" if isinstance(data,list) else type(data).__name__)
     else:
      entries=data if isinstance(data,list) else []
      kustom=[{k:str(v)[:80] for k,v in row.items() if k in ("domain","enabled","disabled","status")} for row in entries if isinstance(row,dict) and "kustomvinyls" in str(row).lower()]
      say("UAPI",cmdname,"exit",status,"status",(obj.get("result") or {}).get("status"),
          "Kustom",kustom[:4],"records",len(entries))
    except Exception as ex:say("UAPI",cmdname,"parseerror",type(ex).__name__,"exit",status)
   else:
    say("SHELL",cmdname,"exit",status,"output",out[:170].replace("\n"," | "),"stderr",err[:120])
  except Exception as ex:say("SHELL",cmdname,"error",type(ex).__name__,str(ex)[:100])
finally:ssh.close()
say("Read only audit complete")
