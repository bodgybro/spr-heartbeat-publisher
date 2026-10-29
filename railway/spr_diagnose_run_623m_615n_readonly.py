#!/usr/bin/env python3
"""Read-only diagnostic 29 Oct Driver run origins/destinations; prints no passwords."""
import os,io,base64,gzip,json,posixpath,hashlib
import paramiko
raw=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode()
key=None
for k in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
 try:key=k.from_private_key(io.StringIO(raw));break
 except Exception:pass
if key is None:raise RuntimeError('SFTP key unavailable')
ssh=paramiko.SSHClient()
ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=os.environ['SFTP_HOST'],username=os.environ['SFTP_USERNAME'],pkey=key,look_for_keys=False,allow_agent=False,timeout=14)
ftp=ssh.open_sftp()
root=os.environ['SFTP_ROOT'].rstrip('/')
if root.endswith('/sps/spr'):root=root[:-4]
elif root.endswith('/public_html'):root+='/sps'
if not root.endswith('/sps'):raise RuntimeError('Unexpected SFTP root')
def get(name):
 with ftp.open(posixpath.join(root,name),'rb') as f:return f.read()
try:
 d=json.loads(gzip.decompress(get('spr/i/d/2026-10-29.json.gz')))
 print('[READ ONLY INDEX]',d.get('date'),d.get('role'),len(d.get('records',[])),len(d.get('pages',[])),d.get('parserBuild'),flush=True)
 recs=d.get('records',[])
 for run in ('623M','615N'):
  selected=[r for r in recs if str(r.get('run','')).upper()==run]
  print('[READ ONLY RUN]',run,len(selected),flush=True)
  for r in selected[:5]:
   keys=('run','crewShift','crew','page','_index','_column','runStartTime','runEndTime','nextDuty','declaredOrigin','runDestination','originTiming','timetableOriginTiming','destinationTiming','formsRun','formsDuty','formsFromDuty','formsDestination','incomingRelieveShift','incomingRelieveLocation')
   print('[RUN DETAILS]',json.dumps({k:r.get(k) for k in keys},ensure_ascii=False)[:1950],flush=True)
   print('[RUN ROWS]',json.dumps({'first':r.get('timetableRows',[])[:4],'last':r.get('timetableRows',[])[-6:]},ensure_ascii=False)[:2500],flush=True)
  preds=[r for r in recs if str(r.get('formsRun','')).upper()==run]
  for r in preds[:4]:
   keys=('run','crewShift','page','_index','runEndTime','runDestination','formsRun','formsFromDuty','formsDuty','formsDestination','formsChain')
   print('[PREDECESSOR]',json.dumps({k:r.get(k) for k in keys},ensure_ascii=False)[:2300],flush=True)
   print('[PREV ROWS]',json.dumps(r.get('timetableRows',[])[-6:],ensure_ascii=False)[:1800],flush=True)
 for r in [x for x in recs if str(x.get('run','')).upper() in ('623M','615N')][:4]:
  num=r.get('page')
  pages=[p for p in d.get('pages',[]) if p.get('page')==num or p.get('pageNo')==num]
  if pages:
   page=pages[0]
   print('[PAGE KEYS]',num,list(page)[:15],flush=True)
   lines=page.get('lines',[])
   sample=[(i,line) for i,line in enumerate(lines) if any(t.lower() in str(line.get('text','')).lower() for t in ('623M','615N','Waterfall','Cronulla','Central ESR','Forms'))]
   print('[PAGE TERMS]',json.dumps(sample[:15],ensure_ascii=False)[:2800],flush=True)
 js=get('script.js')
 print('[JS VERIFIED]',hashlib.sha256(js).hexdigest()[:16], 'formed origin helper present',b'function recoveredFormedRunOrigin(' in js,flush=True)
finally:ftp.close();ssh.close()
