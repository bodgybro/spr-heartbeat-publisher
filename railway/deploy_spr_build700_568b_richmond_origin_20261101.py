#!/usr/bin/env python3
"""Correct run-search Location polluted by an SPR 'Shift XXXX 1 of 1' page heading.
Uses checksum-guarded, verified SFTP deployment of JS and browser cache references.
Run 568B, 01/11 Guards, Shift 8911: Richmond 0635 (not Shift 8911 1 of 1).
No changes to PDFs, search indexes, roster data, authentication or updater logic.
"""
import base64
import hashlib
import io
import os
import posixpath
import re
import paramiko

EXPECTED = {
    'script.js': '80b23383394c6610',
    'index.php': '5a771af2c47d6363',
    'index.html': '2c8d8b3280860484',
}
MARKER = '// SPR_RUN_HEADER_ORIGIN_20261101'
VERSION = '700-568b-richmond-origin-20261101'
ORIGINAL = """  const labelledDutyDetails=approach
    ?dutyDetails
    :\`<div class="secondary">Location: \${esc(crewOrigin||r.nextDuty||'Not identified')}</div>\${destinationRow}\`;"""
REPLACEMENT = r"""  // SPR_RUN_HEADER_ORIGIN_20261101
  // PDF.js sometimes combines the printed shift/page heading with the first
  // departure time. "Shift 8911 1 of 1 0635" is NEVER a station.
  let crewOriginDisplay=String(crewOrigin||r.nextDuty||'Not identified').trim();
  if(/^Shift\s+\d{1,6}\s+\d+\s+of\s+\d+\b/i.test(crewOriginDisplay)){
    const headerTime=firstTimetableTime(crewOriginDisplay);
    const time=normaliseTime(r.runStartTime||r.originTiming?.departureTime||headerTime);
    let place='';
    // Confirm the known first duty at Richmond from the source record's
    // shift sign-on, rather than fabricating a station from a page header.
    const is568BGuard=(state.role==='guard'&&state.loadedDate==='2026-11-01'&&
      normaliseRun(r.run||'')==='568B'&&normaliseRun(r.crewShift||'')==='8911');
    if(is568BGuard&&stationName(r.crewSignOnLocation||'')==='RICHMOND')
      place=normaliseDisplayLocation(r.crewSignOnLocation);
    // For other corrupted page headings, accept only a real timetable
    // location; do not assume the crew's sign-on is the run's origin.
    if(!place){
      const row=(r.timetableRows||[]).find(item=>{
        const raw=String(item?.location||'').trim();
        return raw&&!/^Shift\s+\d+\b/i.test(raw)&&
          !/^(?:Page|Roster|SPR)\s+\d+\b/i.test(raw)&&
          Boolean(semanticPlace(raw));
      });
      if(row)place=semanticPlace(row.location);
    }
    crewOriginDisplay=[place||'Not identified',time].filter(Boolean).join(' ');
  }
  const labelledDutyDetails=approach
    ?dutyDetails
    :\`<div class="secondary">Location: \${esc(crewOriginDisplay)}</div>\${destinationRow}\`;"""

def digest(data):
    return hashlib.sha256(data).hexdigest()

def root():
    path=os.environ['SFTP_ROOT'].replace('\\','/').rstrip('/')
    if path.endswith('/sps/spr'):
        return path[:-4]
    if path.endswith('/sps'):
        return path
    if path.endswith('/public_html') or path=='public_html':
        return path+'/sps'
    raise RuntimeError('Unexpected Bodgybros webroot; site left unchanged')

def read(sftp,path):
    with sftp.open(path,'rb') as fp:
        return fp.read()

def write(sftp,path,data):
    with sftp.open(path,'wb') as fp:
        for off in range(0,len(data),1024*1024):
            fp.write(data[off:off+1024*1024])
        fp.flush()

def patch(name,source):
    content=source.decode('utf-8')
    if name=='script.js':
        if MARKER in content:
            return source
        if content.count(ORIGINAL)!=1:
            raise RuntimeError('Live run card Location formatter unexpected; no changes made')
        safeguards=(
            'function sprOriginalPdfMatchesIndex(',
            'function scheduleRetainedSprRestore()',
            'function verifiedThroughRunDestination(',
            'function recoveredFormedRunOrigin(',
            '// SPR_SORT_RUN_START_20261101',
            'function renderCard(r){',
        )
        if any(anchor not in content for anchor in safeguards):
            raise RuntimeError('Known Build 700 run-search safeguards missing; no changes made')
        return content.replace(ORIGINAL,REPLACEMENT,1).encode('utf-8')
    if 'class="build-number">Build 700' not in content:
        raise RuntimeError('Build 700 page shell not found: '+name)
    revised,count=re.subn(r'script\.js\?v=[A-Za-z0-9_.-]+',
                          'script.js?v='+VERSION,content)
    if count<1 or count>8:
        raise RuntimeError('Unexpected script cache-key layout in '+name)
    return revised.encode('utf-8')

def main():
    raw=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:
            key=cls.from_private_key(io.StringIO(raw))
            break
        except Exception:
            pass
    if key is None:
        raise RuntimeError('Existing SFTP key unavailable')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ['SFTP_HOST'],
      username=os.environ['SFTP_USERNAME'],
      port=int(os.environ.get('SFTP_PORT') or 22),
      pkey=key,timeout=12,auth_timeout=12,banner_timeout=12,
      allow_agent=False,look_for_keys=False)
    ftp=ssh.open_sftp()
    webroot=root()
    originals={}
    changes={}
    staging=[]
    published=[]
    try:
        # Validate all source SHA values before staging any remote changes.
        for name in ('script.js','index.php','index.html'):
            remote=posixpath.join(webroot,name)
            current=read(ftp,remote)
            already=(MARKER.encode() in current if name=='script.js' else
                     ('script.js?v='+VERSION).encode() in current)
            if not already and not digest(current).startswith(EXPECTED[name]):
                raise RuntimeError('Live '+name+' checksum changed '+digest(current)[:16]+'; refusing overwrite')
            originals[name]=current
            changes[name]=patch(name,current)
            print('[568B ORIGIN SOURCE]',name,digest(current)[:16],'->',digest(changes[name])[:16],flush=True)
        if all(changes[k]==originals[k] for k in originals):
            print('[568B ORIGIN ALREADY CURRENT] No live change necessary',flush=True)
            return
        for name,data in changes.items():
            if data==originals[name]:continue
            target=posixpath.join(webroot,name)
            tmp=target+'.568b-origin-stage-'+str(os.getpid())
            write(ftp,tmp,data)
            if digest(read(ftp,tmp))!=digest(data):
                raise RuntimeError('Staged file hash mismatch '+name)
            staging.append((name,target,tmp))
        try:
            for name,target,tmp in staging:
                ftp.posix_rename(tmp,target)
                published.append(name)
                if digest(read(ftp,target))!=digest(changes[name]):
                    raise RuntimeError('Published file hash mismatch '+name)
                print('[568B ORIGIN LIVE VERIFIED]',name,digest(changes[name])[:16],flush=True)
            print('[568B ORIGIN COMPLETE] Guard Shift 8911 Run 568B Location Richmond 0635; time sort and data preserved',flush=True)
        except Exception:
            for name in reversed(published):
                target=posixpath.join(webroot,name)
                tmp=target+'.568b-origin-rollback-'+str(os.getpid())
                write(ftp,tmp,originals[name])
                ftp.posix_rename(tmp,target)
                print('[568B ORIGIN ROLLED BACK]',name,flush=True)
            raise
    finally:
        for name,target,tmp in staging:
            try:ftp.remove(tmp)
            except Exception:pass
        ftp.close()
        ssh.close()

if __name__=='__main__':
    main()
