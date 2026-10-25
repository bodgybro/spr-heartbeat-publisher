#!/usr/bin/env python3
"""Build 684 read-only discovery of live Bodgybros SPR UI/retained loader."""
import os,base64,io,posixpath,re
import paramiko
e=os.environ
ktext=base64.b64decode(e['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
key=None
for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
 try:key=cls.from_private_key(io.StringIO(ktext));break
 except Exception:pass
if not key:raise RuntimeError('Existing SFTP key not recognised')
root=posixpath.normpath(e['SFTP_ROOT'])
if root.endswith('/sps/spr/d') or root.endswith('/sps/spr/g'):root=posixpath.dirname(posixpath.dirname(posixpath.dirname(root)))
elif root.endswith('/sps/spr'):root=posixpath.dirname(root)
elif root.endswith('/public_html'):root=posixpath.join(root,'sps')
if not root.endswith('/sps'):raise RuntimeError('Unexpected primary site root')
ssh=paramiko.SSHClient()
ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
try:
 ssh.connect(hostname=e['SFTP_HOST'],port=int(e.get('SFTP_PORT') or 22),
  username=e['SFTP_USERNAME'],pkey=key,timeout=10,auth_timeout=10,banner_timeout=10,allow_agent=False,look_for_keys=False)
 with ssh.open_sftp() as ftp:
  with ftp.open(posixpath.join(root,'script.js'),'rb') as f:source=f.read().decode('utf-8')
  print('[684 INSPECT] Script size',len(source),flush=True)
  names=[m.group(1) for m in re.finditer(r'\b(?:async\s+)?function\s+([a-zA-Z_$][\w$]*)\s*\(',source) if re.search('restore|activateLoaded|cache|retained|prewarm|original|pdf|shift',m.group(1),re.I)]
  print('[684 INSPECT] Relevant function names:',names[:130],flush=True)
  for marker in ('from this device.','function activateLoadedSprUi(','function scheduleShiftPdfWarmParse(){','async function prepareShiftPdfUrl(shift,onProgress=()=>{}){','async function handleShiftSprClick(event){','SPR_MULTI_STORE','function scheduleActivePdfPrefetch(){'):
   i=source.find(marker)
   print('[684 INSPECT] '+marker[:52]+' at '+str(i),flush=True)
   if i>=0 and marker in ('from this device.','function activateLoadedSprUi('):
    print('[684 INSPECT] nearby code: '+re.sub(r'\s+',' ',source[max(0,i-320):i+530])[:790],flush=True)
finally:ssh.close()
