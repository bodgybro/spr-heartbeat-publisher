#!/usr/bin/env python3
"""One-time read-only packaging of the *live* Bodgybros Build 684.

Reads existing website files over verified SFTP, builds a clean, install-ready
ZIP in memory and uploads only the finished ZIP to /sps/releases/.
No edits to any deployed application files, PDFs, indexes or rosters.
Never bundles credentials, secrets, live roster data or PDF cache.
"""
import os,io,base64,posixpath,hashlib,zipfile,json,time
from pathlib import Path
import paramiko,requests

NAME='SPR-Search-Build-684-Bodgybros.zip'
ROOT_FILES=(
 '.htaccess','admin-api.php','admin.js','auth-api.php',
 'index.html','index.php','roster-cache-api.php','roster-relay-api.php',
 'spr-index-api.php','spr-pdf-sync.php','script.js','style.css',
 'spr-search-logo.gif'
)
UPDATER_FILES=(
 'local-updater/README.txt','local-updater/Reset-SharePoint-Login.cmd',
 'local-updater/SPR-Local-Updater.cmd','local-updater/SPR-Roster-Browser.cmd',
 'local-updater/roster_browser.html','local-updater/spr_local_updater.py'
)
README='''SPR SEARCH — BUILD 684 — BODGYBROS WORKING RELEASE
26 October 2026

This ZIP contains application files retrieved from the live, tested
Bodgybros website. The working Shift-PDF path reuses the cached original
SPR PDF and extracts actual source pages (not rendered images).

INSTALLATION
1. Back up your existing /sps website files.
2. Extract this ZIP DIRECTLY into public_html/sps (or your existing /sps
   website folder). All top-level application files are in the ZIP root.
3. OVERWRITE only matching application files; do not delete data directories.
4. Keep the existing local configuration and credentials in place.
5. Refresh https://www.bodgybros.com/sps/ with Ctrl+Shift+R.
6. Verify Drivers 26/10 -> Adams -> Shift 65, and Drivers 25/10 -> Shift 4222.

INTENTIONALLY EXCLUDED
- /spr/ downloaded Drivers/Guards PDFs, prepared search indexes and old
  server-side shift caches; they remain on the website and are generated
  by the existing updater.
- /rosters/ and /.roster-cache/ data (preserve existing contents).
- roster-server-config.php and all account credentials/secrets.
- local-updater/config.json (preserve your existing local config).
- Obsolete Kustom Vinyls dual-site endpoints and blocked shift-manifest
  workaround. Bodgybros is the only publishing website.

The Railway SPR/roster updater is deployed and configured SEPARATELY.
This ZIP is the Bodgybros SPR Search website plus non-secret local updater
tools, not a backup of Railway environment variables or secrets.

Do NOT re-enable Build 680/681 server-side shift-PDF extraction.
Maintain Build 684 original-PDF page copying and its IndexedDB PDF cache.
'''
def checksum(data):return hashlib.sha256(data).hexdigest()
def root_path(p):
 p=posixpath.normpath(p.replace('\\','/').strip())
 if p.endswith('/sps/spr/d') or p.endswith('/sps/spr/g'):
  p=posixpath.dirname(posixpath.dirname(posixpath.dirname(p)))
 elif p.endswith('/sps/spr'):p=posixpath.dirname(p)
 elif p.endswith('/public_html'):p=posixpath.join(p,'sps')
 if not p.endswith('/sps'):raise RuntimeError('Unrecognised Bodgybros SFTP website root')
 return p
def read(sftp,p):
 with sftp.open(p,'rb') as file:return file.read()
def main():
 e=os.environ
 for v in ('SFTP_HOST','SFTP_USERNAME','SFTP_PRIVATE_KEY_B64','SFTP_ROOT'):
  if not e.get(v):raise RuntimeError('Missing established SFTP credential setting '+v)
 raw=base64.b64decode(e['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
 key=None
 for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
  try:key=typ.from_private_key(io.StringIO(raw));break
  except Exception:pass
 if key is None:raise RuntimeError('Existing primary SFTP private key unavailable')
 hosts='/data/credentials/spr-sftp-known_hosts'
 if not Path(hosts).is_file():raise RuntimeError('Pinned SFTP host key missing')
 ssh=paramiko.SSHClient()
 ssh.load_host_keys(hosts)
 ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
 site=root_path(e['SFTP_ROOT'])
 try:
  ssh.connect(hostname=e['SFTP_HOST'],port=int(e.get('SFTP_PORT') or 22),
    username=e['SFTP_USERNAME'],pkey=key,timeout=12,auth_timeout=12,
    banner_timeout=12,allow_agent=False,look_for_keys=False)
  with ssh.open_sftp() as sftp:
   buf=io.BytesIO()
   checks={}
   with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
    z.writestr('README-BUILD-684.txt',README)
    for name in ROOT_FILES+UPDATER_FILES:
     try:
      data=read(sftp,posixpath.join(site,name))
     except FileNotFoundError:
      if name in ('script.js','index.php','index.html','style.css'):
       raise RuntimeError('Required live application file missing: '+name)
      print('[684 ZIP] Optional file missing, skipped: '+name,flush=True)
      continue
     # Defense-in-depth for accidental secret/config file names.
     if any(x in name.lower() for x in ('.env','secret','password','token','server-config','credentials','config.json')):
      raise RuntimeError('Sensitive file attempted in release: '+name)
     if len(data)>12_000_000:raise RuntimeError('Unexpectedly large website file: '+name)
     if name=='script.js':
      if (b'SPR_RESTORED_SHIFT_LOADER_684' not in data or
          b'SPR_BUILD683_RESTORED_650_FAST_SHIFT_CACHE' not in data or
          b'copyPages(source,pages.map(p=>p-1))' not in data):
       raise RuntimeError('Live script.js does not contain confirmed Build 684 original-page extraction')
     z.writestr(name,data)
     checks[name]=checksum(data)
    z.writestr('SHA256SUMS.json',json.dumps(checks,indent=2,sort_keys=True)+'\n')
   blob=buf.getvalue()
   with zipfile.ZipFile(io.BytesIO(blob)) as check:
    err=check.testzip()
    if err:raise RuntimeError('ZIP integrity verification failed on '+err)
    all_names=check.namelist()
    if 'app/' in all_names or any(name.startswith('app/') for name in all_names):
     raise RuntimeError('Unexpected duplicate app folder in release')
    print('[684 ZIP CREATED] files='+str(len(all_names))+' archiveBytes='+str(len(blob))+' SHA256='+checksum(blob),flush=True)
   releases=posixpath.join(site,'releases')
   try:sftp.stat(releases)
   except FileNotFoundError:sftp.mkdir(releases)
   target=posixpath.join(releases,NAME)
   partial=target+'.uploading'
   try:
    with sftp.open(partial,'wb') as out:out.write(blob)
    with sftp.open(partial,'rb') as f:uploaded=f.read()
    if checksum(uploaded)!=checksum(blob):raise RuntimeError('Remote release ZIP SHA256 mismatch')
    sftp.posix_rename(partial,target)
    with sftp.open(target,'rb') as f:final=f.read()
    if checksum(final)!=checksum(blob):raise RuntimeError('Final release ZIP SHA256 mismatch')
   finally:
    try:sftp.remove(partial)
    except Exception:pass
   print('[684 ZIP VERIFIED ON BODGYBROS] '+target+' bytes='+str(len(blob)),flush=True)
 finally:ssh.close()
 url='https://www.bodgybros.com/sps/releases/'+NAME
 try:
  r=requests.get(url,stream=True,timeout=(8,20),allow_redirects=False)
  magic=next(r.iter_content(chunk_size=8),b'')
  print('[684 ZIP PUBLIC DOWNLOAD] status='+str(r.status_code)+
    ' type='+str(r.headers.get('Content-Type',''))[:50]+
    ' firstBytesPK='+str(magic.startswith(b'PK'))+
    ' length='+str(r.headers.get('Content-Length','')),flush=True)
  r.close()
 except Exception as err:print('[684 ZIP PUBLIC DOWNLOAD] probe error '+str(err)[:160],flush=True)
if __name__=='__main__':main()
