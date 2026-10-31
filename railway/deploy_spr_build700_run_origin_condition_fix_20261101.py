#!/usr/bin/env python3
"""Repair two date-dependent run-origin display branches in live Build 700.

Only the frontend origin display conditions change. Guard by live SHA-256,
stage all assets, verify staged+published hashes, rollback on failure.
The actual SPR source confirms 01/11 Guards:
  578B / Shift 8064 - Forms at Liverpool 0539.
  568B / Shift 8911 - Richmond 0635.
Do not modify any SPR PDF, cached roster, search index or updater engine.
"""
import base64,hashlib,io,os,posixpath,re
import paramiko

EXPECTED={
 "script.js":"753e1137004a081f",
 "index.php":"5abb79d98310489f",
 "index.html":"b45d7fc2fbd42040",
}
VERSION="700-run-origin-verified-20261101-v2"
MARKER="// SPR_568B_578B_ORIGIN_CONDITION_V2"

OLD_578="""  const verified578B=state.role==='guard'&&state.loadedDate==='2026-11-01'&&
    normaliseRun(r.run||'')==='578B'&&normaliseRun(r.crewShift||'')==='8064'&&
    firstTimetableTime(crewOriginDisplay)==='0539';
  if(originMissing&&verified578B)crewOriginDisplay='Liverpool 0539';"""
NEW_578=r"""  // SPR_568B_578B_ORIGIN_CONDITION_V2
  // This record has already been verified against the original 1/11 Guards
  // SPR: Shift 8064 Forms 578B at Liverpool 0539. Never depend on
  // state.loadedDate: it is not the loaded source's date in the live reader.
  const verified578B=String(r.run||'').replace(/\s+/g,'').toUpperCase()==='578B'&&
    String(r.crewShift||'').trim()==='8064'&&
    /^not\s+identified\b/i.test(crewOriginDisplay)&&
    /\b0539\b/.test(crewOriginDisplay);
  if(verified578B)crewOriginDisplay='Liverpool 0539';"""

OLD_568="""    const is568BGuard=(state.role==='guard'&&state.loadedDate==='2026-11-01'&&
      normaliseRun(r.run||'')==='568B'&&normaliseRun(r.crewShift||'')==='8911');
    if(is568BGuard&&stationName(r.crewSignOnLocation||'')==='RICHMOND')
      place=normaliseDisplayLocation(r.crewSignOnLocation);"""
NEW_568=r"""    const is568BGuard=String(r.run||'').replace(/\s+/g,'').toUpperCase()==='568B'&&
      String(r.crewShift||'').trim()==='8911'&&
      /\b0635\b/.test(crewOriginDisplay);
    if(is568BGuard)place='Richmond';"""

def sha(b):return hashlib.sha256(b).hexdigest()
def sftp_root():
    root=os.environ['SFTP_ROOT'].replace('\\','/').rstrip('/')
    if root.endswith('/sps/spr'):return root[:-4]
    if root.endswith('/sps'):return root
    if root.endswith('/public_html') or root=='public_html':return root+'/sps'
    raise RuntimeError('Unexpected Bodgybros SFTP root')
def read(ftp,path):
    with ftp.open(path,'rb') as f:return f.read()
def write(ftp,path,data):
    with ftp.open(path,'wb') as f:
        for i in range(0,len(data),1024*1024):f.write(data[i:i+1024*1024])
        f.flush()
def patch(name,data):
    s=data.decode('utf-8')
    if name=='script.js':
        if MARKER in s:return data
        for old in (OLD_568,OLD_578):
            if s.count(old)!=1:raise RuntimeError('Exact old origin condition not found; leaving site unchanged')
        for must in ('function renderCard(r){',
                     '// SPR_SORT_RUN_START_20261101',
                     '// SPR_RUN_HEADER_ORIGIN_20261101',
                     'SPR_MISSING_RUN_ORIGIN_FROM_TIMETABLE_20261101',
                     'function sprOriginalPdfMatchesIndex('):
            if must not in s:raise RuntimeError('Known working frontend safeguard missing: '+must)
        return s.replace(OLD_568,NEW_568,1).replace(OLD_578,NEW_578,1).encode('utf-8')
    if 'class="build-number">Build 700' not in s:raise RuntimeError('Unexpected shell build label')
    revised,n=re.subn(r'script\.js\?v=[A-Za-z0-9_.-]+','script.js?v='+VERSION,s)
    if not (1<=n<=8):raise RuntimeError('Script cache key count unexpected')
    return revised.encode('utf-8')
def main():
    private=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(private));break
        except Exception:pass
    if key is None:raise RuntimeError('Existing SFTP key invalid')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ['SFTP_HOST'],username=os.environ['SFTP_USERNAME'],
       port=int(os.environ.get('SFTP_PORT') or 22),pkey=key,
       timeout=12,auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
    ftp=ssh.open_sftp()
    root=sftp_root()
    original={};fresh={};staged=[];published=[]
    try:
        for name in ('script.js','index.php','index.html'):
            dest=posixpath.join(root,name)
            old=read(ftp,dest)
            already=(MARKER.encode() in old if name=='script.js' else ('script.js?v='+VERSION).encode() in old)
            if not already and not sha(old).startswith(EXPECTED[name]):
                raise RuntimeError('Live '+name+' checksum unexpected '+sha(old)[:16]+'; no site writes')
            original[name]=old;fresh[name]=patch(name,old)
            print('[RUN ORIGIN V2 SOURCE]',name,sha(old)[:16],'=>',sha(fresh[name])[:16],flush=True)
        if all(fresh[k]==original[k] for k in original):
            print('[RUN ORIGIN V2 ALREADY CURRENT]',flush=True);return
        for name,data in fresh.items():
            if data==original[name]:continue
            dest=posixpath.join(root,name)
            temp=dest+'.run-origin-v2-stage-'+str(os.getpid())
            write(ftp,temp,data)
            if sha(read(ftp,temp))!=sha(data):raise RuntimeError('Staged file hash verification failed')
            staged.append((name,dest,temp))
        try:
            for name,dest,temp in staged:
                ftp.posix_rename(temp,dest);published.append(name)
                if sha(read(ftp,dest))!=sha(fresh[name]):raise RuntimeError('Live file hash verification failed')
                print('[RUN ORIGIN V2 LIVE VERIFIED]',name,sha(fresh[name])[:16],flush=True)
            print('[RUN ORIGIN V2 COMPLETE] 578B Shift 8064 Liverpool 0539; 568B Shift 8911 Richmond 0635. Ordering and stored PDFs unchanged.',flush=True)
        except Exception:
            for name in reversed(published):
                dest=posixpath.join(root,name)
                temp=dest+'.run-origin-v2-rollback-'+str(os.getpid())
                write(ftp,temp,original[name]);ftp.posix_rename(temp,dest)
                print('[RUN ORIGIN V2 ROLLBACK]',name,flush=True)
            raise
    finally:
        for name,dest,temp in staged:
            try:ftp.remove(temp)
            except Exception:pass
        ftp.close();ssh.close()
if __name__=='__main__':main()
