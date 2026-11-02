#!/usr/bin/env python3
"""Read-only inspect 3 Nov Drivers 623G SPR and live iPhone roster index logic."""
import os,io,base64,posixpath,re,hashlib,time
from pypdf import PdfReader
import paramiko
e=os.environ
root=e['SFTP_ROOT'].replace('\\','/').rstrip('/')
if root.endswith('/sps/spr'):root=root[:-4]
elif root.endswith('/sps'):pass
elif root in ('public_html',) or root.endswith('/public_html'):root+='/sps'
else:raise RuntimeError('Site root unexpected')
raw=base64.b64decode(e['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
key=None
for kind in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=kind.from_private_key(io.StringIO(raw));break
    except Exception:pass
if key is None:raise RuntimeError('Existing SFTP key unavailable')
ssh=paramiko.SSHClient()
ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=e['SFTP_HOST'],username=e['SFTP_USERNAME'],port=int(e.get('SFTP_PORT') or 22),
            pkey=key,allow_agent=False,look_for_keys=False,timeout=12,auth_timeout=12,banner_timeout=12)
try:
    with ssh.open_sftp() as ftp:
        with ftp.open(posixpath.join(root,'script-700-578b-location-v3.js'),'rb') as f:buf=f.read()
        js=buf.decode('utf-8')
        print('[623G AUDIT JS SHA]',hashlib.sha256(buf).hexdigest()[:32],flush=True)
        for needle in ('function verifiedMissingRunOriginFromTimetable(record){',
                       'function recoveredFormedRunOrigin(',
                       'function renderCard(r){',
                       'function rosterPreloadAllDailyRosters(',
                       'async function rosterBuildDailyShiftIndex(',
                       'async function rosterSearchShift('):
            k=js.find(needle)
            print('[623G AUDIT ANCHOR]',needle,k,flush=True)
            if k<0:continue
            if 'renderCard' in needle:
                render=js[k:k+18000]
                for sub in ('let crewOriginDisplay=','const labelledDutyDetails=','function verifiedMissingRunOriginFromTimetable','return card;'):
                    j=render.find(sub)
                    if j>=0:print('[623G AUDIT RENDER]',sub,repr(render[max(0,j-500):j+1800]),flush=True)
            elif 'rosterBuildDailyShiftIndex' in needle:
                code=js[k:k+7000]
                print('[623G AUDIT BUILDER INTRO]',repr(code[:1450]),flush=True)
                print('[623G AUDIT BUILDER END]',repr(code[-2150:]),flush=True)
            elif 'recoveredFormed' in needle or 'verifiedMissingRunOrigin' in needle:
                print('[623G AUDIT HELPER]',needle,repr(js[k:k+4400]),flush=True)
        filename='All Drivers Combined 03_11_2026.pdf'
        path=posixpath.join(root,'spr','d',filename)
        st=ftp.stat(path)
        print('[623G AUDIT PDF]',filename,'bytes',st.st_size,flush=True)
        with ftp.open(path,'rb') as f:data=f.read()
    start=time.time()
    reader=PdfReader(io.BytesIO(data),strict=False)
    print('[623G AUDIT PAGECOUNT]',len(reader.pages),flush=True)
    found=0
    for page_no,page in enumerate(reader.pages,1):
        raw=page.extract_text() or ''
        if not re.search(r'\b623\s*G\b',raw,re.I):continue
        lines=[x.strip() for x in raw.splitlines() if x.strip()]
        relevant=[i for i,x in enumerate(lines) if re.search(r'\b623\s*G\b',x,re.I)]
        for i in relevant[:3]:
            print('[623G AUDIT PAGE]',page_no,'line',i,'context',
                  repr(lines[max(0,i-14):min(len(lines),i+21)]),flush=True)
        found+=1
        if found>=8:break
        if time.time()-start>110:
            print('[623G AUDIT PDF TIME BOUND]',page_no,flush=True)
            break
    print('[623G AUDIT PDF DONE]','matching pages',found,'seconds',round(time.time()-start,1),flush=True)
finally:
    ssh.close()
