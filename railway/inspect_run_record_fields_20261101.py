#!/usr/bin/env python3
"""Read only: identify field names used by live Run Search card and sorting."""
import os,base64,posixpath,io,re,hashlib
import paramiko
e=os.environ;root=e['SFTP_ROOT'].replace('\\','/').rstrip('/')
if root.endswith('/sps/spr'):root=root[:-4]
elif root.endswith('/sps'):pass
elif root.endswith('/public_html') or root=='public_html':root+='/sps'
else:raise RuntimeError('Unexpected site root')
raw=base64.b64decode(e['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
key=None
for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=cls.from_private_key(io.StringIO(raw));break
    except Exception:pass
if key is None:raise RuntimeError('No existing SSH key')
ssh=paramiko.SSHClient();ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=e['SFTP_HOST'],username=e['SFTP_USERNAME'],port=int(e.get('SFTP_PORT') or 22),pkey=key,
           timeout=12,auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
ftp=ssh.open_sftp()
try:
    with ftp.open(posixpath.join(root,'script.js'),'rb') as f: buf=f.read()
    js=buf.decode('utf-8');print('[FIELD AUDIT SHA]',hashlib.sha256(buf).hexdigest()[:32],flush=True)
    for tag,size in (('function renderCard(r){',11500),('function searchRun(value){',6100),
                     ('function searchRun(',4100),('function recordTime(record){',1500),
                     ('function chronologicalRecordValue(record,anchor){',1800)):
        i=js.find(tag);print('[FIELD AUDIT SECTION]',tag,'pos',i,flush=True)
        if i>=0:print('[FIELD AUDIT SOURCE]',tag,repr(js[i:i+size]),flush=True)
    for pat in ('crewShift', 'runNumber','runId','crewShiftNumber','shiftNumber',
                'runStartTime', 'run:', 'crewName:', 'name:', 'runNo:'):
        offsets=[m.start() for m in list(re.finditer(re.escape(pat),js))]
        print('[FIELD AUDIT TOKEN]',pat,'count',len(offsets), 'samples',
              [repr(js[max(0,p-90):p+140]) for p in offsets[:3]],flush=True)
except Exception as exc:
    print('[FIELD AUDIT ERROR]',type(exc).__name__,str(exc)[:180],flush=True)
    raise
finally:
    ftp.close();ssh.close()
