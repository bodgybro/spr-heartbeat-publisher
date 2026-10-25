#!/usr/bin/env python3
"""Read-only 26 October Driver/Guard SOURCE PDF identity diagnostic.
Sample PDF text via PyMuPDF in Railway, never print personal names or
authentication details. Original files never modified.
"""
import os,io,base64,posixpath,hashlib,re,time
import paramiko
import fitz
def read_remote(ftp,path):
 size=ftp.stat(path).st_size
 with ftp.open(path,'rb') as f:
  f.prefetch(file_size=size,max_concurrent_requests=16)
  data=f.read()
 if len(data)!=size:raise RuntimeError('Remote file size changed')
 return data
def classify(text):
 text=re.sub(r'\s+',' ',text[:1200])
 head=text[:240]
 counts={k:len(re.findall(r'\b'+k+r'\b',text,re.I)) for k in ('Driver','Guard','Drivers','Guards','Sydney Trains','Shift')}
 titles=re.findall(r'Sydney\s+Trains?\s+(?:Driver|Guard)\b',text,re.I)
 return {'head':head,'titles':titles[:5],'counts':counts}
def main():
 e=os.environ;key_text=base64.b64decode(e['SFTP_PRIVATE_KEY_B64']).decode()
 k=None
 for cl in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
  try:k=cl.from_private_key(io.StringIO(key_text));break
  except:pass
 ssh=paramiko.SSHClient()
 ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
 ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
 try:
  ssh.connect(hostname=e['SFTP_HOST'],port=int(e.get('SFTP_PORT') or 22),username=e['SFTP_USERNAME'],pkey=k,timeout=12,auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
  root=posixpath.normpath(e['SFTP_ROOT'].replace('\\','/'))
  if root.endswith('/sps/spr/d') or root.endswith('/sps/spr/g'):root=posixpath.dirname(posixpath.dirname(posixpath.dirname(root)))
  elif root.endswith('/sps/spr'):root=posixpath.dirname(root)
  elif root.endswith('/public_html'):root=posixpath.join(root,'sps')
  if not root.endswith('/sps'):raise RuntimeError('Unexpected primary root')
  with ssh.open_sftp() as ftp:
   for role,title in [('d','Drivers'),('g','Guards')]:
    p=posixpath.join(root,'spr',role,'All '+title+' Combined 26_10_2026.pdf')
    b=read_remote(ftp,p)
    pdf=fitz.open(stream=b,filetype='pdf')
    print('[SOURCE ID] role='+role+' bytes='+str(len(b))+' sha256='+hashlib.sha256(b).hexdigest()[:16]+' pages='+str(pdf.page_count),flush=True)
    for n in (0,1,2,5,20,91,233):
     if n>=pdf.page_count:continue
     text=pdf[n].get_text(sort=True)
     print('[SOURCE PAGE] role='+role+' page='+str(n+1)+' '+str(classify(text))[:580],flush=True)
    pdf.close()
 finally:ssh.close()
if __name__=='__main__':main()
