#!/usr/bin/env python3
"""READ ONLY: inspect live Guards 1/11 578B origin and parser source.

No website writes, no credential output. Prints only shift 8064 run 578B page
and relevant JS renderer section, suppressing unrelated crews and shifts.
"""
import base64,hashlib,io,os,posixpath,re
from pypdf import PdfReader
import paramiko
env=os.environ
root=env['SFTP_ROOT'].replace('\\','/').rstrip('/')
if root.endswith('/sps/spr'):root=root[:-4]
elif root.endswith('/sps'):pass
elif root.endswith('/public_html') or root=='public_html':root+='/sps'
else:raise RuntimeError('Unrecognised SPR SFTP root')
keytext=base64.b64decode(env['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
key=None
for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=cls.from_private_key(io.StringIO(keytext));break
    except Exception:pass
if key is None:raise RuntimeError('Could not use existing SFTP key')
ssh=paramiko.SSHClient()
ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=env['SFTP_HOST'],port=int(env.get('SFTP_PORT') or 22),
            username=env['SFTP_USERNAME'],pkey=key,
            timeout=12,auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
ftp=ssh.open_sftp()
try:
    with ftp.open(posixpath.join(root,'script.js'),'rb') as f:js=f.read().decode('utf-8')
    print('[578B LIVE JS SHA]',hashlib.sha256(js.encode()).hexdigest()[:32],flush=True)
    for needle in ('function renderCard(r){','function semanticOriginFromEvidence(record){',
                   'function parsedRunOrigin','function dutyLocation('):
        ix=js.find(needle)
        print('[578B JS MARKER]',needle,ix,flush=True)
        if ix>=0 and needle=='function renderCard(r){':
            segment=js[ix:ix+8200]
            j=segment.find('const parsedOrigin=')
            print('[578B LIVE RENDERER]',repr(segment[max(0,j-150):j+3100]),flush=True)
    target=posixpath.join(root,'spr','g','All Guards Combined 01_11_2026.pdf')
    print('[578B SOURCE FOUND]',ftp.stat(target).st_size,flush=True)
    with ftp.open(target,'rb') as f:data=f.read()
    print('[578B PDF DOWNLOADED]',len(data),flush=True)
    reader=PdfReader(io.BytesIO(data),strict=False)
    print('[578B PDF PAGECOUNT]',len(reader.pages),flush=True)
    matching=[]
    for i,page in enumerate(reader.pages):
        raw=page.extract_text() or ''
        if re.search(r'\b8064\b',raw) and ('578B' in raw.upper().replace(' ','') or
             re.search(r'SHIFT\s+8064\b',raw,re.I)):
            matching.append((i,raw))
            if len(matching)>=3:break
    print('[578B MATCH PAGES]',[p+1 for p,_ in matching],flush=True)
    for p,raw in matching:
        lines=[x.strip() for x in raw.splitlines() if x.strip()]
        n=next((n for n,x in enumerate(lines) if '578B' in x.upper().replace(' ','')),0)
        print('[578B PDF PAGE]',p+1,'lines',len(lines),flush=True)
        for i in range(max(0,n-26),min(len(lines),n+48)):
            print('[578B PDF DUTY LINE]',str(i)+':',lines[i][:180],flush=True)
finally:
    ftp.close();ssh.close()
