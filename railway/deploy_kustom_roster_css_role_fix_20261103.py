#!/usr/bin/env python3
"""One-time Kustom-only role CSS correction. Preserve everything else."""
import os, paramiko, pathlib, hashlib, posixpath, shlex, stat
from datetime import datetime, timezone
ROOT='/home10/kustomvi/public_html/sps'
BACKUP='/home10/kustomvi/.spr-rc1-backups/roster-role-css'
OLD='html[data-spr-admin="1"] #protectedRosterBrowser{display:block!important}'
NEW=('html[data-spr-admin="1"][data-spr-role="admin"] #protectedRosterBrowser:not(.hidden),\\n'
     'html[data-spr-admin="1"][data-spr-role="dt"] #protectedRosterBrowser:not(.hidden),\\n'
     'html[data-spr-admin="1"][data-spr-role="standard"] #protectedRosterBrowser:not(.hidden){display:block!important}\\n'
     'html[data-spr-role="demo"] #protectedRosterBrowser,\\n'
     'html[data-spr-role="basic"] #protectedRosterBrowser{display:none!important}')
# Explicit newlines rather than double escaped sequences.
NEW=NEW.replace('\\n','\n')
def out(*msg):print('[KUSTOM ROSTER ROLE FIX]',*msg,flush=True)
def digest(data):return hashlib.sha256(data).hexdigest()
def sha(ssh,p):
 i,o,e=ssh.exec_command('sha256sum -- '+shlex.quote(p),timeout=18)
 text=o.read(125).decode('ascii','replace')
 if o.channel.recv_exit_status()!=0 or len(text)<64:raise RuntimeError('Remote SHA unavailable')
 return text[:64]
def main():
 key='/data/credentials/kustom-transfer/id_ed25519'
 known='/data/credentials/kustom-transfer/known_hosts'
 if not pathlib.Path(key).is_file() or not pathlib.Path(known).is_file():raise RuntimeError('Known SSH credentials missing')
 ssh=paramiko.SSHClient();ssh.load_host_keys(known);ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
 ssh.connect(hostname='cp-wc18.per01.ds.network',username='kustomvi',port=22,
    pkey=paramiko.Ed25519Key.from_private_key_file(key),timeout=14,banner_timeout=14,auth_timeout=14,
    look_for_keys=False,allow_agent=False)
 with ssh:
  with ssh.open_sftp() as ftp:
   originals={}
   for name in ('style.css','index.php'):
    path=posixpath.join(ROOT,name)
    with ftp.open(path,'rb') as f:data=f.read()
    if sha(ssh,path)!=digest(data):raise RuntimeError('Preflight integrity failed: '+name)
    originals[name]=data
   css=originals['style.css'].decode('utf-8')
   html=originals['index.php'].decode('utf-8')
   if OLD in css:
    if css.count(OLD)!=1:raise RuntimeError('Unexpected original CSS count')
    css=css.replace(OLD,NEW)
   elif NEW in css:
    out('CSS selectors already corrected')
   else:raise RuntimeError('Unknown CSS roster visibility version; no changes')
   if '#protectedRosterBrowser{display:none!important}' not in css:raise RuntimeError('Missing base roster hide rule')
   if 'data-spr-role="demo"' not in css or 'data-spr-role="basic"' not in css:raise RuntimeError('Missing restricted roles')
   import re
   # Bust old stylesheets on all clients; preserve other website imports.
   newhtml,count=re.subn(r'style\\.css\\?v=[A-Za-z0-9._-]+','style.css?v=700-role-roster-css-v3',html,count=1)
   if count!=1:raise RuntimeError('Expected one versioned CSS link')
   if 'id="protectedRosterBrowser"' not in newhtml:raise RuntimeError('Roster element absent')
   updated={'style.css':css.encode('utf-8'),'index.php':newhtml.encode('utf-8')}
   changed=[n for n in updated if updated[n]!=originals[n]]
   if not changed:out('Already applied and verified');return
   for folder in ('/home10/kustomvi/.spr-rc1-backups',BACKUP):
    try:ftp.mkdir(folder,mode=0o700)
    except IOError:
     if not stat.S_ISDIR(ftp.stat(folder).st_mode):raise
   for name in changed:
    target=posixpath.join(BACKUP,name+'.before-20261103')
    try:ftp.stat(target);raise RuntimeError('Backup path already exists: '+name)
    except FileNotFoundError:pass
    with ftp.open(target,'wb') as f:f.write(originals[name])
    if sha(ssh,target)!=digest(originals[name]):raise RuntimeError('Backup SHA mismatch: '+name)
   out('Preflight passed; remote backups verified')
   written=[]
   try:
    for name in changed:
     dest=posixpath.join(ROOT,name);stage=dest+'.role-css-staged'
     with ftp.open(stage,'wb') as f:f.write(updated[name])
     ftp.chmod(stage,0o644)
     if sha(ssh,stage)!=digest(updated[name]):raise RuntimeError('Stage SHA mismatch: '+name)
     ftp.posix_rename(stage,dest)
     written.append(name)
     if sha(ssh,dest)!=digest(updated[name]):raise RuntimeError('Published SHA mismatch: '+name)
     out('Verified',name)
    i,o,e=ssh.exec_command('php -l '+shlex.quote(posixpath.join(ROOT,'index.php')),timeout=20)
    line=(o.read(400)+e.read(400)).decode('utf-8','replace')
    if o.channel.recv_exit_status()!=0:raise RuntimeError('PHP lint failed: '+line[:150])
    out('SUCCESS: Demo/Basic roster section hidden, Standard/DT/Admin permitted')
   except Exception:
    for name in reversed(written):
     dest=posixpath.join(ROOT,name)
     with ftp.open(dest,'wb') as f:f.write(originals[name])
     out('ROLLED BACK',name,sha(ssh,dest)==digest(originals[name]))
    raise
if __name__=='__main__':
 try:main()
 except Exception as exc:
  out('FAILED',type(exc).__name__,str(exc)[:180])
  raise
