#!/usr/bin/env python3
"""Publish a private-link-style single-click ZIP download page for Build 684.

The hosting WAF returns 406 for directly served .zip archives. We keep the
exact SHA-verified live Build 684 ZIP intact and expose a tokenized HTML page
and same-origin JS script that saves those bytes as the proper .zip filename.
No changes to the active SPR Search frontend or Railway updater.
"""
import os,io,base64,hashlib,html,zipfile,secrets,posixpath
import paramiko,requests

ARCHIVE='SPR-Search-Build-684-Bodgybros.zip'
def sha(b):return hashlib.sha256(b).hexdigest()
def read(sftp,p):
 with sftp.open(p,'rb') as f:return f.read()
def write(sftp,p,data):
 tmp=p+'.stage684'
 try:
  with sftp.open(tmp,'wb') as w:w.write(data)
  if sha(read(sftp,tmp))!=sha(data):raise RuntimeError('SFTP staging checksum mismatch')
  sftp.posix_rename(tmp,p)
  if sha(read(sftp,p))!=sha(data):raise RuntimeError('SFTP published checksum mismatch')
 finally:
  try:sftp.remove(tmp)
  except Exception:pass
def rootpath(raw):
 p=posixpath.normpath(raw.strip().replace('\\','/'))
 if p.endswith('/sps/spr/d') or p.endswith('/sps/spr/g'):p=posixpath.dirname(posixpath.dirname(posixpath.dirname(p)))
 elif p.endswith('/sps/spr'):p=posixpath.dirname(p)
 elif p.endswith('/public_html'):p=posixpath.join(p,'sps')
 if not p.endswith('/sps'):raise RuntimeError('Unknown site root')
 return p
def main():
 env=os.environ
 for name in ('SFTP_HOST','SFTP_USERNAME','SFTP_PRIVATE_KEY_B64','SFTP_ROOT'):
  if not env.get(name):raise RuntimeError('Required site connection '+name+' missing')
 key_text=base64.b64decode(env['SFTP_PRIVATE_KEY_B64']).decode('utf8')
 key=None
 for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
  try:key=cls.from_private_key(io.StringIO(key_text));break
  except Exception:pass
 if key is None:raise RuntimeError('Cannot parse existing SFTP key')
 ssh=paramiko.SSHClient()
 ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
 ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
 try:
  ssh.connect(hostname=env['SFTP_HOST'],port=int(env.get('SFTP_PORT') or 22),
              username=env['SFTP_USERNAME'],pkey=key,timeout=12,auth_timeout=12,
              banner_timeout=12,allow_agent=False,look_for_keys=False)
  with ssh.open_sftp() as sftp:
   folder=posixpath.join(rootpath(env['SFTP_ROOT']),'releases')
   data=read(sftp,posixpath.join(folder,ARCHIVE))
   if not data.startswith(b'PK\x03\x04'):raise RuntimeError('Verified ZIP magic missing')
   with zipfile.ZipFile(io.BytesIO(data)) as z:
    if z.testzip():raise RuntimeError('Live ZIP archive integrity check failed')
    if 'script.js' not in z.namelist() or 'index.php' not in z.namelist():
     raise RuntimeError('Build 684 full website files missing from ZIP')
    if b'SPR_RESTORED_SHIFT_LOADER_684' not in z.read('script.js'):
     raise RuntimeError('Requested working Build 684 Shift loader not present')
   package_sha=sha(data)
   token=secrets.token_hex(12)
   stem='build684-'+token
   js_name=stem+'.js'
   html_name=stem+'.html'
   # Emit manageable 16KB JS string chunks rather than a giant HTML href.
   pieces=[base64.b64encode(data).decode('ascii')[i:i+16384]
        for i in range(0,len(base64.b64encode(data)),16384)]
   literals=',\n'.join('"'+x+'"' for x in pieces)
   js='''"use strict";
(() => {
const parts = [
'''+literals+'''
];
const archiveName = "'''+ARCHIVE+'''";
const status=document.getElementById("status");
const download=document.getElementById("getZip");
download.addEventListener("click", () => {
  try {
    download.disabled=true;
    status.textContent="Preparing verified ZIP download…";
    const binary=atob(parts.join(""));
    const bytes=new Uint8Array(binary.length);
    for(let i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);
    if(bytes[0]!==80 || bytes[1]!==75)throw new Error("Archive header incorrect");
    const blob=new Blob([bytes],{type:"application/zip"});
    const url=URL.createObjectURL(blob);
    const a=document.createElement("a");
    a.href=url;a.download=archiveName;document.body.appendChild(a);a.click();a.remove();
    status.textContent="Your Build 684 ZIP download has started.";
    setTimeout(()=>URL.revokeObjectURL(url),60000);
  }catch(e){status.textContent="Download failed: "+e.message;download.disabled=false;}
});
})();
'''
   page='''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SPR Search Build 684 ZIP</title>
<style>body{font:16px system-ui,sans-serif;max-width:620px;margin:9vh auto;padding:20px;color:#193044;line-height:1.65}button{font:600 17px system-ui;background:#164e9e;color:white;border:0;border-radius:9px;padding:14px 22px;cursor:pointer}button:disabled{opacity:.6}code{overflow-wrap:anywhere}small{color:#617386}</style>
</head><body><h1>SPR Search — Build 684</h1>
<p>This is a ZIP of the confirmed working Bodgybros website files. It contains the original Shift PDF page extractor and browser cache.</p>
<p><button type="button" id="getZip">Download Build 684 ZIP</button></p>
<p id="status" role="status">Ready to download the exact verified release.</p>
<p><small>Archive size: '''+str(len(data))+''' bytes<br>SHA-256: <code>'''+package_sha+'''</code><br>
Credentials, stored rosters and downloaded SPR PDFs are not included.</small></p>
<script defer src="./'''+js_name+'''"></script></body></html>'''
   write(sftp,posixpath.join(folder,js_name),js.encode('utf8'))
   write(sftp,posixpath.join(folder,html_name),page.encode('utf8'))
   print('[684 ZIP DOWNLOAD PAGE UPLOADED] '+html_name+' JS bytes '+str(len(js))+' exact_zip_sha256 '+package_sha,flush=True)
 finally:ssh.close()
 link='https://www.bodgybros.com/sps/releases/'+html_name
 js_link='https://www.bodgybros.com/sps/releases/'+js_name
 for u in (link,js_link):
  try:
   r=requests.get(u,timeout=(7,18),stream=True,allow_redirects=False)
   first=next(r.iter_content(chunk_size=512),b'')
   print('[684 RELEASE PUBLIC TEST] '+('HTML' if u==link else 'JS')+' HTTP '+str(r.status_code)+' contentType '+str(r.headers.get('Content-Type'))+
     ' bytes '+str(r.headers.get('Content-Length'))+' bodyOk '+str((b'<!DOCTYPE html>' in first) if u==link else (b'"use strict"' in first)),flush=True)
   r.close()
  except Exception as exc:print('[684 RELEASE PUBLIC TEST] '+str(exc)[:160],flush=True)
 print('[684 DOWNLOAD LINK] '+link,flush=True)
if __name__=='__main__':main()
