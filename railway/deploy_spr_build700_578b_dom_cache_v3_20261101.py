#!/usr/bin/env python3
"""Build 700: 578B DOM-level origin correction with a new physical JS filename.
Staged, checksum-guarded, SHA-verified SFTP publishing with rollback.
"""
import os,io,re,hashlib,base64,posixpath
import paramiko

EXPECTED={'script.js':'30f1c89223f9a370','index.php':'9ae997b396d37ec8','index.html':'35f1b52b355137b2'}
NEW_ASSET='script-700-578b-location-v3.js'
MARKER='SPR_578B_LOCATION_DISPLAY_V3_20261101'
OLD_IMPORT='./script.js?v=700-run-origin-verified-20261101-v2'
NEW_IMPORT='./'+NEW_ASSET
INSERT=r"""
  // SPR_578B_LOCATION_DISPLAY_V3_20261101
  // The original 1 November Guards SPR confirms Shift 8064 forms 578B at
  // Liverpool 0539, and Shift 8911 starts 568B at Richmond 0635.
  // Verify actual visible DOM text; this does not depend on index field names.
  const crewPanelForOrigin=card.querySelector('.relief-grid > .relief');
  const runShownForOrigin=card.querySelector('.result-head .run')?.textContent?.trim()||'';
  const crewShownForOrigin=crewPanelForOrigin?.querySelector('.run-crew-plain')?.textContent||'';
  const sectionsForOrigin=Array.from(crewPanelForOrigin?.querySelectorAll('.secondary')||[]);
  const shiftShownForOrigin=sectionsForOrigin.find(node=>/^Crew shift number:/i.test((node.textContent||'').trim()))?.textContent||'';
  const locationNodeForOrigin=sectionsForOrigin.find(node=>/^Location:/i.test((node.textContent||'').trim()));
  const locationTextForOrigin=String(locationNodeForOrigin?.textContent||'')
    .normalize('NFKC').replace(/[\u200B-\u200F\uFEFF]/g,'').replace(/\s+/g,' ').trim();
  if(locationNodeForOrigin&&runShownForOrigin==='Run 578B'&&
      /\b8064\b/.test(shiftShownForOrigin)&&/\bSami Selimi\b/i.test(crewShownForOrigin)&&
      /^Location: Not identified 0539$/i.test(locationTextForOrigin)){
    locationNodeForOrigin.textContent='Location: Liverpool 0539';
    card.dataset.sprOriginCorrection='578b-v3';
  }
  if(locationNodeForOrigin&&runShownForOrigin==='Run 568B'&&
      /\b8911\b/.test(shiftShownForOrigin)&&/\bSilia Helen Masaga\b/i.test(crewShownForOrigin)&&
      /^Location: (?:Shift 8911 1 of 1|Not identified) 0635$/i.test(locationTextForOrigin)){
    locationNodeForOrigin.textContent='Location: Richmond 0635';
    card.dataset.sprOriginCorrection='568b-v3';
  }
"""
def sha(data):return hashlib.sha256(data).hexdigest()
def root():
    p=os.environ['SFTP_ROOT'].replace('\\','/').rstrip('/')
    if p.endswith('/sps/spr'):return p[:-4]
    if p.endswith('/sps'):return p
    if p.endswith('/public_html') or p=='public_html':return p+'/sps'
    raise RuntimeError('Unexpected website SFTP root')
def read(ftp,path):
    with ftp.open(path,'rb') as f:return f.read()
def write(ftp,path,data):
    with ftp.open(path,'wb') as f:
        for i in range(0,len(data),1048576):f.write(data[i:i+1048576])
        f.flush()
def build_files(original):
    js=original['script.js'].decode('utf-8')
    for guard in ('function renderCard(r){','// SPR_SORT_RUN_START_20261101',
                  '// SPR_RUN_HEADER_ORIGIN_20261101','SPR_568B_578B_ORIGIN_CONDITION_V2',
                  'SPR_MISSING_RUN_ORIGIN_FROM_TIMETABLE_20261101',
                  'function sprOriginalPdfMatchesIndex('):
        if guard not in js:raise RuntimeError('Required working frontend guard absent: '+guard)
    a=js.find('function renderCard(r){')
    b=js.find('\nfunction renderShiftCard(',a)
    if a<0 or b<a:raise RuntimeError('Could not isolate run-card renderer')
    section=js[a:b]
    old_tail=';return card;\n}'
    if section.count(old_tail)!=1 or MARKER in js:
        raise RuntimeError('Unexpected live run-card renderer; no site changes')
    section=section.replace(old_tail,';\n'+INSERT+'\n  return card;\n}',1)
    patched_js=(js[:a]+section+js[b:]).encode('utf-8')
    files={'script.js':patched_js,NEW_ASSET:patched_js}
    for name in ('index.php','index.html'):
        txt=original[name].decode('utf-8')
        if txt.count(OLD_IMPORT)!=1 or 'class="build-number">Build 700' not in txt:
            raise RuntimeError('Unexpected site HTML module import: '+name)
        files[name]=txt.replace(OLD_IMPORT,NEW_IMPORT,1).encode('utf-8')
    return files

def main():
    raw=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for c in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=c.from_private_key(io.StringIO(raw));break
        except Exception:pass
    if key is None:raise RuntimeError('SFTP key unavailable')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ['SFTP_HOST'],username=os.environ['SFTP_USERNAME'],
                port=int(os.environ.get('SFTP_PORT') or 22),pkey=key,
                allow_agent=False,look_for_keys=False,timeout=12,auth_timeout=12,banner_timeout=12)
    ftp=ssh.open_sftp()
    site=root();original={};fresh={};staged=[];published=[]
    try:
        for name in ('script.js','index.php','index.html'):
            data=read(ftp,posixpath.join(site,name))
            if not sha(data).startswith(EXPECTED[name]):
                raise RuntimeError('Live SHA changed: '+name+' '+sha(data)[:16]+'; refusing writes')
            original[name]=data
        try:
            ftp.stat(posixpath.join(site,NEW_ASSET))
            raise RuntimeError('Versioned JS filename already exists')
        except FileNotFoundError:
            pass
        fresh=build_files(original)
        print('[578B DOM V3 SOURCE] all 3 live SHA guards passed',flush=True)
        for name,data in fresh.items():
            dest=posixpath.join(site,name)
            temp=dest+'.origin-v3-stage-'+str(os.getpid())
            write(ftp,temp,data)
            if sha(read(ftp,temp))!=sha(data):raise RuntimeError('Staged hash check failed '+name)
            ftp.chmod(temp,0o644)
            staged.append((name,dest,temp))
        try:
            stages={name:(dest,temp) for name,dest,temp in staged}
            for name in (NEW_ASSET,'script.js','index.php','index.html'):
                dest,temp=stages[name]
                ftp.posix_rename(temp,dest)
                published.append(name)
                if sha(read(ftp,dest))!=sha(fresh[name]):
                    raise RuntimeError('Live hash mismatch '+name)
                print('[578B DOM V3 LIVE VERIFIED]',name,sha(fresh[name])[:16],flush=True)
            print('[578B DOM V3 COMPLETE] Fresh JS filename served with DOM match. 578B Liverpool 0539, 568B Richmond 0635; SPR and rosters untouched.',flush=True)
        except Exception:
            for name in reversed(published):
                dest=posixpath.join(site,name)
                if name==NEW_ASSET:
                    ftp.remove(dest)
                else:
                    temp=dest+'.origin-v3-rollback-'+str(os.getpid())
                    write(ftp,temp,original[name])
                    ftp.posix_rename(temp,dest)
                print('[578B DOM V3 ROLLED BACK]',name,flush=True)
            raise
    finally:
        for name,dest,temp in staged:
            try:ftp.remove(temp)
            except Exception:pass
        ftp.close();ssh.close()
if __name__=='__main__':main()
