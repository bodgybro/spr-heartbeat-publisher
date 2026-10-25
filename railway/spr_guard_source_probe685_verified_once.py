#!/usr/bin/env python3
import os,base64,io,posixpath,hashlib,re,traceback,time
import paramiko
print('[SOURCE685 CHECK START] runtime ok',flush=True)
try:
 import fitz
 print('[SOURCE685 CHECK] PyMuPDF loaded',flush=True)
 e=os.environ
 ktxt=base64.b64decode(e['SFTP_PRIVATE_KEY_B64']).decode()
 key=None
 for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
  try:key=typ.from_private_key(io.StringIO(ktxt));break
  except Exception:pass
 if key is None:raise RuntimeError('SFTP private key not available')
 ssh=paramiko.SSHClient()
 ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
 ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
 print('[SOURCE685 CHECK] connecting verified SFTP',flush=True)
 ssh.connect(hostname=e['SFTP_HOST'],port=int(e.get('SFTP_PORT') or 22),username=e['SFTP_USERNAME'],pkey=key,timeout=12,auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
 r=posixpath.normpath(e['SFTP_ROOT'])
 if r.endswith('/sps/spr/d') or r.endswith('/sps/spr/g'):r=posixpath.dirname(posixpath.dirname(posixpath.dirname(r)))
 elif r.endswith('/sps/spr'):r=posixpath.dirname(r)
 elif r.endswith('/public_html'):r=posixpath.join(r,'sps')
 if not r.endswith('/sps'):raise RuntimeError('wrong SFTP dir')
 print('[SOURCE685 CHECK] SFTP connected',flush=True)
 with ssh.open_sftp() as ftp:
  ftp.get_channel().settimeout(45)
  for role,title in (('g','Guards'),('d','Drivers')):
   path=posixpath.join(r,'spr',role,'All '+title+' Combined 26_10_2026.pdf')
   size=ftp.stat(path).st_size
   print('[SOURCE685 READING] role='+role+' size='+str(size),flush=True)
   f=ftp.open(path,'rb')
   f.prefetch(file_size=size,max_concurrent_requests=16)
   data=f.read()
   f.close()
   print('[SOURCE685 DOWNLOAD] role='+role+' received='+str(len(data))+' sha='+hashlib.sha256(data).hexdigest()[:16],flush=True)
   pdf=fitz.open(stream=data,filetype='pdf')
   headers=[]
   for i in (0,1,2,3,20,91):
    if i>=pdf.page_count:continue
    t=pdf[i].get_text(sort=True)[:750]
    types=re.findall(r'Sydney\s+Trains?\s+(Driver|Guard)\b',t,re.I)
    secondary=[w for w in ['Driver','Guard','Drivers','Guards'] if re.search(r'\b'+w+r'\b',t,re.I)]
    headers.append({'page':i+1,'sourceHeadings':types[:3],'keywords':secondary})
   print('[SOURCE685 IDENTIFIED] role='+role+' pagecount='+str(pdf.page_count)+' pages='+repr(headers),flush=True)
   pdf.close()
 ssh.close()
except Exception as exc:
 print('[SOURCE685 CHECK FAILED] '+type(exc).__name__+' '+str(exc)[:180],flush=True)
 raise
