#!/usr/bin/env python3
"""One-time Kustom Vinyls demo Roster Browser visibility fix.
Strictly edits index.php and admin.js after independent backup. No credentials embedded.
"""
import os, sys, pathlib, posixpath, hashlib, datetime, stat, subprocess, tempfile
import paramiko

ROOT='/home10/kustomvi/public_html/sps'
HOME='/home10/kustomvi'
CHANGES={
 'admin.js':(
  "if(rosterProtected)rosterProtected.classList.toggle('hidden',!ok);",
  "if(rosterProtected)rosterProtected.classList.toggle('hidden',!ok||role==='demo');"
 ),
 'index.php':(
  '<section id="protectedRosterBrowser" class="hidden" aria-label="Protected roster browser">',
  '<section id="protectedRosterBrowser" class="hidden" aria-label="Protected roster browser"<?php if (spr_session_role() === \'demo\'): ?> style="display:none !important"<?php endif; ?>>'
 )
}
def sha(v):return hashlib.sha256(v).hexdigest()
def say(*args):print('[KUSTOM DEMO HIDE]',*args,flush=True)
def remote_sha(ssh,path):
 cmd='sha256sum -- '+__import__('shlex').quote(path)
 i,o,e=ssh.exec_command(cmd,timeout=20)
 response=o.read(128).decode('ascii','replace'); rc=o.channel.recv_exit_status()
 if rc or len(response)<64:raise RuntimeError('Remote checksum failed')
 return response[:64]
def main():
 key='/data/credentials/kustom-transfer/id_ed25519'
 known='/data/credentials/kustom-transfer/known_hosts'
 if not (pathlib.Path(key).is_file() and pathlib.Path(known).is_file()):
  raise RuntimeError('Pinned secondary SSH credentials unavailable')
 ssh=paramiko.SSHClient()
 ssh.load_host_keys(known);ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
 ssh.connect(hostname='cp-wc18.per01.ds.network',username='kustomvi',port=22,
             pkey=paramiko.Ed25519Key.from_private_key_file(key),
             timeout=12,banner_timeout=12,auth_timeout=12,look_for_keys=False,allow_agent=False)
 backup_dir=HOME+'/.spr-rc1-backups/demo-browser-20261103'
 written=[]
 originals={}
 with ssh:
  with ssh.open_sftp() as ftp:
   for name,(old,new) in CHANGES.items():
    remote=posixpath.join(ROOT,name)
    with ftp.open(remote,'rb') as f: raw=f.read()
    if sha(raw)!=remote_sha(ssh,remote):raise RuntimeError(name+' preflight hash mismatch')
    source=raw.decode('utf-8')
    if new in source and old not in source:
     say(name,'already fixed');continue
    if source.count(old)!=1 or new in source:
     raise RuntimeError(name+' unexpected version; no changes applied')
    modified=source.replace(old,new,1).encode('utf-8')
    originals[name]=(raw,modified)
   if not originals:
    say('Already fixed on Kustom; no writes needed');return
   if len(originals)!=2:raise RuntimeError('Partial live version mismatch; not writing')
   for directory in (HOME+'/.spr-rc1-backups',backup_dir):
    try:ftp.mkdir(directory,mode=0o700)
    except OSError:
     if not stat.S_ISDIR(ftp.stat(directory).st_mode):raise
   for name,(raw,modified) in originals.items():
    backup=posixpath.join(backup_dir,name)
    with ftp.open(backup,'wb') as f:f.write(raw)
    if remote_sha(ssh,backup)!=sha(raw):raise RuntimeError('Backup verification failed for '+name)
   say('Both original files backed up outside webroot and SHA-verified')
   try:
    for name,(raw,modified) in originals.items():
     remote=posixpath.join(ROOT,name); temp=remote+'.demo-fix-stage'
     with ftp.open(temp,'wb') as f:f.write(modified)
     ftp.chmod(temp,0o644)
     if remote_sha(ssh,temp)!=sha(modified):raise RuntimeError('Stage SHA failed for '+name)
     ftp.posix_rename(temp,remote)
     written.append(name)
     if remote_sha(ssh,remote)!=sha(modified):raise RuntimeError('Live SHA failed for '+name)
     say(name,'updated and verified')
    cmd='php -l '+__import__('shlex').quote(posixpath.join(ROOT,'index.php'))
    i,o,e=ssh.exec_command(cmd,timeout=20)
    out=o.read(500).decode('utf-8','replace');err=e.read(500).decode('utf-8','replace')
    if o.channel.recv_exit_status()!=0:raise RuntimeError('PHP lint failed: '+(err or out)[:150])
    say('PHP syntax verified; Demo Roster Browser hidden; DT/Admin retained')
   except Exception:
    for name in reversed(written):
     remote=posixpath.join(ROOT,name);raw=originals[name][0]
     with ftp.open(remote,'wb') as f:f.write(raw)
     if remote_sha(ssh,remote)!=sha(raw):say('CRITICAL rollback verification failed',name)
     else:say('Restored original',name)
    raise
if __name__=='__main__':
 try: main()
 except Exception as ex:
  say('ERROR',type(ex).__name__,str(ex)[:240])
  raise
