#!/usr/bin/env python3
"""READ ONLY live JS source inspection for iOS roster shift 224 03/11 tab crash."""
import os,io,base64,posixpath,re,hashlib,paramiko
env=os.environ
root=env['SFTP_ROOT'].replace('\\','/').rstrip('/')
if root.endswith('/sps/spr'):root=root[:-4]
elif not root.endswith('/sps') and (root.endswith('/public_html') or root=='public_html'):root+='/sps'
elif not root.endswith('/sps'):raise RuntimeError('Unrecognised site root')
raw=base64.b64decode(env['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
key=None
for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=cls.from_private_key(io.StringIO(raw));break
    except Exception:pass
if not key:raise RuntimeError('Existing SFTP key unavailable')
ssh=paramiko.SSHClient()
ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=env['SFTP_HOST'],username=env['SFTP_USERNAME'],port=int(env.get('SFTP_PORT') or 22),
            pkey=key,timeout=10,auth_timeout=10,banner_timeout=10,look_for_keys=False,allow_agent=False)
try:
    with ssh.open_sftp() as ftp:
        with ftp.open(posixpath.join(root,'script-700-578b-location-v3.js'),'rb') as f:buf=f.read()
finally:ssh.close()
js=buf.decode('utf-8')
print('[SHIFT MEMORY AUDIT SHA]',hashlib.sha256(buf).hexdigest()[:32],flush=True)
names=['rosterPreloadAllDailyRosters','rosterWarmAllDailyShiftSearch','rosterGetDailyShiftIndex',
       'rosterBuildDailyShiftIndex','rosterSearchShift','rosterLoadSprShiftIndex','rosterPrepareSprShiftPdf',
       'rosterLoadPdfSnapshot','rosterLoadPdf','rosterLoadSprIndex','rosterGetCachedPdf']
all_functions=list(re.finditer(r'(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(',js))
for name in names:
    hits=[(m.start(),m.end()) for m in all_functions if m.group(1)==name]
    if len(hits)!=1:
        print('[SHIFT MEMORY NO FUNCTION]',name,len(hits),flush=True);continue
    start=hits[0][0]
    following=[m.start() for m in all_functions if m.start()>start]
    end=min(following) if following else len(js)
    snippet=js[start:end]
    max_chars=10500 if name in ('rosterGetDailyShiftIndex','rosterSearchShift','rosterWarmAllDailyShiftSearch','rosterPreloadAllDailyRosters') else 7500
    print('[SHIFT MEMORY FUNCTION]',name,'pos',start,'len',len(snippet),flush=True)
    # Emit complete when modest, otherwise first and last sections with line separators
    if len(snippet)>max_chars:
        chunk=snippet[:max_chars//2]+'\n\n---- MIDDLE OMITTED ----\n\n'+snippet[-max_chars//2:]
    else:chunk=snippet
    for i in range(0,len(chunk),4000):
        print('[SHIFT MEMORY SOURCE]',name,'part',i//4000,repr(chunk[i:i+4000]),flush=True)
for needle in ('rosterDailyShiftIndexMemory','rosterAllDailyPreloads','rosterPdfMemoryCache',
               'Promise.all(', 'rosterWarmAllDailyShiftSearch()', 'rosterPrepareSprShiftPdf('):
    print('[SHIFT MEMORY COUNT]',needle,js.count(needle),flush=True)
