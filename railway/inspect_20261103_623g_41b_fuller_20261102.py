#!/usr/bin/env python3
"""Read-only inspect the 3 Nov Drivers SPR and current shift-card renderer.
No changes to site or PDFs. Bounded work for Railway startup health.
"""
import os, io, base64, hashlib, posixpath, re, importlib.util, shutil, time
import paramiko
e=os.environ
root=e['SFTP_ROOT'].replace('\\','/').rstrip('/')
if root.endswith('/sps/spr'): root=root[:-4]
elif root.endswith('/sps'): pass
elif root.endswith('/public_html') or root=='public_html': root+='/sps'
else: raise RuntimeError('Invalid site root')
raw=base64.b64decode(e['SFTP_PRIVATE_KEY_B64']).decode()
key=None
for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=cls.from_private_key(io.StringIO(raw));break
    except Exception:pass
if key is None:raise RuntimeError('Invalid SFTP key')
ssh=paramiko.SSHClient()
ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=e['SFTP_HOST'],username=e['SFTP_USERNAME'],pkey=key,
            port=int(e.get('SFTP_PORT') or 22),timeout=12,auth_timeout=12,
            banner_timeout=12,allow_agent=False,look_for_keys=False)
try:
    with ssh.open_sftp() as ftp:
        with ftp.open(posixpath.join(root,'script-700-578b-location-v3.js'),'rb') as f:jsbuf=f.read()
        print('[3NOV AUDIT JS SHA]',hashlib.sha256(jsbuf).hexdigest()[:32],flush=True)
        js=jsbuf.decode('utf-8')
        for needle in ('function renderShiftCard(shift){','function renderCard(r){',
                       'function dutyLocation(', 'function semanticPlace('):
            a=js.find(needle);print('[3NOV AUDIT FUNC]',needle,'offset',a,flush=True)
            if a<0:continue
            if 'renderShiftCard' in needle:
                sect=js[a:a+30000]
                for pat in ('Relieve','relieve','Location:', 'reliefLocation','dutyLocation(', 'original'):
                    for m in list(re.finditer(re.escape(pat),sect,re.I))[:8]:
                        i=m.start()
                        print('[3NOV AUDIT SHIFT RENDER]',pat,repr(sect[max(0,i-280):i+470]),flush=True)
            elif 'renderCard' in needle:
                sect=js[a:a+9000]
                for pat in ('crewOrigin','parsedOrigin','reliefLocation', 'destination'):
                    k=sect.find(pat)
                    if k>=0: print('[3NOV AUDIT RUN RENDER]',pat,repr(sect[max(0,k-90):k+400]),flush=True)
        with ftp.open(posixpath.join(root,'spr','d','All Drivers Combined 03_11_2026.pdf'),'rb') as f:
            data=f.read()
        print('[3NOV AUDIT PDF]',len(data),'bytes; fitz',bool(importlib.util.find_spec('fitz')),'pdftotext',shutil.which('pdftotext') or 'no',flush=True)
    if importlib.util.find_spec('fitz'):
        import fitz
        doc=fitz.open(stream=data,filetype='pdf')
        print('[3NOV AUDIT PAGES]',doc.page_count,flush=True)
        started=time.monotonic(); results={'623G':0,'Fuller':0}
        for page_idx in range(doc.page_count):
            if time.monotonic()-started>85:break
            txt=doc[page_idx].get_text('text',sort=True)
            lines=[x.strip() for x in txt.splitlines() if x.strip()]
            for pattern,label in ((r'\b623[\s-]*G\b','623G'),(r'\bFuller\b','Fuller')):
                match=[j for j,x in enumerate(lines) if re.search(pattern,x,re.I)]
                if match and results[label]<5:
                    for j in match[:2]:
                        print('[3NOV AUDIT PDF MATCH]',label,'page',page_idx+1,
                              'lines',repr(lines[max(0,j-15):min(len(lines),j+25)]),flush=True)
                    results[label]+=1
            if all(v>=5 for v in results.values()):break
        print('[3NOV AUDIT PDF RESULTS]',results,'elapsed',round(time.monotonic()-started,1),flush=True)
    else:
        print('[3NOV AUDIT PDF SKIP] No fast PDF text engine; defer large PDF scan',flush=True)
finally:
    ssh.close()
