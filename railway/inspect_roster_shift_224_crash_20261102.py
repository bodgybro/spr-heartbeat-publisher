#!/usr/bin/env python3
"""Read-only diagnostic for iPhone roster shift 224, 3 Nov, in live JS.
No roster/SPR data or website files modified.
"""
import os,io,base64,posixpath,hashlib,re,collections
import paramiko
env=os.environ;root=env['SFTP_ROOT'].replace('\\','/').rstrip('/')
if root.endswith('/sps/spr'):root=root[:-4]
elif root.endswith('/sps'):pass
elif root.endswith('/public_html') or root=='public_html':root+='/sps'
else:raise RuntimeError('Unknown site root')
keyblob=base64.b64decode(env['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
key=None
for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=cls.from_private_key(io.StringIO(keyblob));break
    except Exception:pass
if key is None:raise RuntimeError('Existing SFTP key invalid')
ssh=paramiko.SSHClient()
ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=env['SFTP_HOST'],username=env['SFTP_USERNAME'],
    port=int(env.get('SFTP_PORT') or 22),pkey=key,timeout=10,auth_timeout=10,
    banner_timeout=10,allow_agent=False,look_for_keys=False)
try:
    ftp=ssh.open_sftp()
    try:
        with ftp.open(posixpath.join(root,'script-700-578b-location-v3.js'),'rb') as handle:
            buf=handle.read()
    finally:ftp.close()
finally:ssh.close()
js=buf.decode('utf-8')
print('[ROSTER SHIFT AUDIT] live script length',len(js),'SHA',hashlib.sha256(buf).hexdigest()[:24],flush=True)
for match in re.finditer(r'(?:async\s+)?function\s+([A-Za-z][A-Za-z0-9_]*)\s*\(',js):
    name=match.group(1)
    if ('roster' in name.lower() and any(part in name.lower() for part in ('shift','search','find','fetch','load','render','result','parse','pdf'))) or name in ('searchShift','searchRosters'):
        print('[ROSTER SHIFT FUNCTION]',name,match.start(),flush=True)
for needle in (
    'rosterShiftSearch','rosterAdvancedSearchShift','rosterSearchShift',
    'rosterShiftSearchHandler','rosterAdvancedUi.shiftSearch',
    'rosterAdvancedUi.shiftDate','rosterCanonicalShiftId',
    'rosterIsSupportedShiftId','rosterSetStatus',
    'Searching all Daily', 'Shift search', 'shift-search',
    'rosterShiftQuery','async function rosterSearch'
):
    arr=[m.start() for m in re.finditer(re.escape(needle),js,re.I)]
    print('[ROSTER SHIFT NEEDLE]',needle,'hits',len(arr),'first',arr[:7],flush=True)
    for offset in arr[:2]:
        print('[ROSTER SHIFT EXCERPT]',needle,repr(js[max(0,offset-1000):offset+2200]),flush=True)
