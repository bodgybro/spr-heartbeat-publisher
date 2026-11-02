#!/usr/bin/env python3
"""Read-only audit of live From-To dropdown options. No SFTP writes."""
import os,io,base64,posixpath,re,hashlib,paramiko
env=os.environ
root=env['SFTP_ROOT'].replace('\\','/').rstrip('/')
if root.endswith('/sps/spr'):root=root[:-4]
elif root.endswith('/sps'):pass
elif root.endswith('/public_html') or root=='public_html':root+='/sps'
else:raise RuntimeError('Unexpected SFTP root')
secret=base64.b64decode(env['SFTP_PRIVATE_KEY_B64']).decode()
key=None
for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=typ.from_private_key(io.StringIO(secret));break
    except Exception:pass
if key is None:raise RuntimeError('No SFTP key')
ssh=paramiko.SSHClient()
ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=env['SFTP_HOST'],username=env['SFTP_USERNAME'],port=int(env.get('SFTP_PORT') or 22),pkey=key,
            allow_agent=False,look_for_keys=False,timeout=12)
try:
    with ssh.open_sftp() as ftp:
        with ftp.open(posixpath.join(root,'script-700-mobile-224-3nov-v1.js'),'rb') as f:b=f.read()
        with ftp.open(posixpath.join(root,'index.html'),'rb') as f:html=f.read().decode('utf-8')
finally:ssh.close()
js=b.decode('utf-8')
print('[STATION AUDIT SHA]',hashlib.sha256(b).hexdigest(),len(b),flush=True)
for term in ['From time','To time','From–To','From-To','fromLocation','toLocation','fromStation','toStation',
             'routeLocations','stationOptions','stationList','locationOptions','fromTo','from-to',
             'From location','To location','stationName','allStations']:
    matches=list(re.finditer(re.escape(term),js,re.I))
    print('[STATION AUDIT TOKEN]',term,'count',len(matches),'pos',[m.start() for m in matches[:7]],flush=True)
    for m in matches[:3]:
        off=m.start()
        print('[STATION AUDIT CONTEXT]',term,repr(js[max(0,off-500):off+950]),flush=True)
for m in re.finditer(r'(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(',js):
    name=m.group(1)
    if ('station' in name.lower() or 'fromto' in name.lower() or 'location' in name.lower()) and len(name)>5:
        print('[STATION AUDIT FUNCTION]',name,m.start(),flush=True)
for term in ['From location','To location','From-To','From to','From time']:
    for m in list(re.finditer(re.escape(term),html,re.I))[:2]:
        print('[STATION AUDIT HTML]',term,repr(html[max(0,m.start()-260):m.start()+650]),flush=True)
