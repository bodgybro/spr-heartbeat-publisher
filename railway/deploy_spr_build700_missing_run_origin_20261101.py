#!/usr/bin/env python3
"""Verified live frontend fix: recover real run origin from matching timetable.

Preserves original SPR PDFs, roster files, cached index, date/role state and
run-result chronology. Rejects later stops that do not match the run start.
"""
import base64, hashlib, io, os, posixpath, re
import paramiko

EXPECTED={
 "script.js":"1fa54ee7424839d1",
 "index.php":"4d1bc08f1bc4f6e2",
 "index.html":"61d21cbe0c7053ce",
}
OLD="  let crewOriginDisplay=String(crewOrigin||r.nextDuty||'Not identified').trim();"
NEW="""  let crewOriginDisplay=String(crewOrigin||r.nextDuty||'Not identified').trim();
  if(!r.incomingRelieveShift&&
      /^(?:not identified|unknown)(?:\\s+[0-2]\\d[0-5]\\d)?$/i.test(crewOriginDisplay)){
    const recovered=verifiedMissingRunOriginFromTimetable(r);
    if(recovered)crewOriginDisplay=recovered;
  }"""
HELPER=r"""// SPR_MISSING_RUN_ORIGIN_FROM_TIMETABLE_20261101
// The printed shift heading or a missing Trip Origin is not a station.
// Use a real first stop with a time matching this specific run's start;
// never substitute the crew's depot, sign-on or a later intermediate stop.
function verifiedMissingRunOriginFromTimetable(record){
  const start=normaliseTime(record?.runStartTime||record?.originTiming?.departureTime||'');
  const startMinutes=minutesFromTime(start);
  if(!Number.isFinite(startMinutes))return '';
  const validStation=value=>{
    const raw=String(value||'').trim();
    if(!raw||/^(?:not identified|unknown|shift\s+\d+|page\s+\d+)\b/i.test(raw))return '';
    const station=semanticPlace(raw);
    return station&&isUsableTimetableLocation(station)&&
      !/^(?:not identified|unknown|shift\s+\d+|page\s+\d+)\b/i.test(station)
      ?normaliseDisplayLocation(station):'';
  };
  const matchesTime=value=>minutesFromTime(normaliseTime(value||''))===startMinutes;
  // Read physical timetable rows first; these retain the station separately
  // even when a PDF text header has polluted originTiming or nextDuty.
  for(const row of record?.timetableRows||[]){
    const station=validStation(row?.location);
    if(!station)continue;
    const candidates=[
      row?.departureTime,
      row?.arrivalTime,
      ...(Array.isArray(row?.times)?row.times:[]),
      preferredDepartureTime(row)
    ];
    if(candidates.some(matchesTime))return [station,start].join(' ');
    // Refuse a later stop even if it is the first parsed row.
  }
  // The original run evidence may retain the first station at its departure
  // time even where PDF.js did not build a structured timetable row.
  const evidence=semanticOriginFromEvidence(record);
  if(evidence&&matchesTime(evidence.departureTime)){
    const station=validStation(evidence.location);
    if(station)return [station,start].join(' ');
  }
  return '';
}
"""
def digest(buf):return hashlib.sha256(buf).hexdigest()
def site_root():
    root=os.environ['SFTP_ROOT'].replace('\\','/').rstrip('/')
    if root.endswith('/sps/spr'):return root[:-4]
    if root.endswith('/sps'):return root
    if root.endswith('/public_html') or root=='public_html':return root+'/sps'
    raise RuntimeError('Unexpected SFTP root, refusing changes')
def read(sftp,path):
    with sftp.open(path,'rb') as file:return file.read()
def write(sftp,path,data):
    with sftp.open(path,'wb') as file:
        for offset in range(0,len(data),1024*1024):
            file.write(data[offset:offset+1024*1024])
        file.flush()
def patch(name,data):
    text=data.decode('utf-8')
    if name=='script.js':
        if 'SPR_MISSING_RUN_ORIGIN_FROM_TIMETABLE_20261101' in text:return data
        if text.count(OLD)!=1 or text.count('function renderCard(r){')!=1:
            raise RuntimeError('Unexpected live run renderer; no changes')
        for token in ('function sprOriginalPdfMatchesIndex(',
                      'function scheduleRetainedSprRestore()',
                      'function semanticOriginFromEvidence(record){',
                      'function preferredDepartureTime(row){',
                      '// SPR_SORT_RUN_START_20261101',
                      '// SPR_RUN_HEADER_ORIGIN_20261101'):
            if token not in text:raise RuntimeError('Working guard missing: '+token)
        updated=text.replace('function renderCard(r){',HELPER+'\nfunction renderCard(r){',1).replace(OLD,NEW,1)
        return updated.encode('utf-8')
    if 'class="build-number">Build 700' not in text:raise RuntimeError('Expected Build 700 label missing')
    updated,count=re.subn(r'script\.js\?v=[A-Za-z0-9_.-]+',
        'script.js?v=700-missing-run-origin-20261101',text)
    if count<1 or count>8:raise RuntimeError('Unexpected cache references')
    return updated.encode('utf-8')
def main():
    private_key=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=typ.from_private_key(io.StringIO(private_key));break
        except Exception:pass
    if key is None:raise RuntimeError('Existing SFTP key invalid')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ['SFTP_HOST'],username=os.environ['SFTP_USERNAME'],
      port=int(os.environ.get('SFTP_PORT') or 22),pkey=key,
      timeout=12,auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
    ftp=ssh.open_sftp();root=site_root()
    original={};fresh={};staged=[];published=[]
    try:
        for name in ('script.js','index.php','index.html'):
            path=posixpath.join(root,name)
            old=read(ftp,path)
            already=('SPR_MISSING_RUN_ORIGIN_FROM_TIMETABLE_20261101' in old.decode('utf-8')
                  if name=='script.js' else 'script.js?v=700-missing-run-origin-20261101' in old.decode('utf-8'))
            if not already and not digest(old).startswith(EXPECTED[name]):
                raise RuntimeError('Live checksum not expected: '+name+' '+digest(old)[:16])
            original[name]=old;fresh[name]=patch(name,old)
            print('[RUN ORIGIN SOURCE]',name,digest(old)[:16],'=>',digest(fresh[name])[:16],flush=True)
        if all(original[k]==fresh[k] for k in original):
            print('[RUN ORIGIN ALREADY CURRENT]',flush=True);return
        for name,new in fresh.items():
            if new==original[name]:continue
            dest=posixpath.join(root,name);temp=dest+'.run-origin-stage-'+str(os.getpid())
            write(ftp,temp,new)
            if digest(read(ftp,temp))!=digest(new):raise RuntimeError('Staged hash mismatch '+name)
            staged.append((name,dest,temp))
        try:
            for name,dest,temp in staged:
                ftp.posix_rename(temp,dest)
                published.append(name)
                if digest(read(ftp,dest))!=digest(fresh[name]):raise RuntimeError('Published hash mismatch '+name)
                print('[RUN ORIGIN LIVE VERIFIED]',name,digest(fresh[name])[:16],flush=True)
            print('[RUN ORIGIN PATCH COMPLETE] Matching first timetable row fallback published; no SPR or roster changes',flush=True)
        except Exception:
            for name in reversed(published):
                dest=posixpath.join(root,name);rollback=dest+'.run-origin-rollback-'+str(os.getpid())
                write(ftp,rollback,original[name]);ftp.posix_rename(rollback,dest)
                print('[RUN ORIGIN ROLLED BACK]',name,flush=True)
            raise
    finally:
        for name,dest,temp in staged:
            try:ftp.remove(temp)
            except Exception:pass
        ftp.close();ssh.close()
if __name__=='__main__':main()
