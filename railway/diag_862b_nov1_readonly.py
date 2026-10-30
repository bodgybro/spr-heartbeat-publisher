#!/usr/bin/env python3
"""READ ONLY: inspect active Run 862B Nov 1 2026 published index and Build 700 run renderer.
No secrets printed, no website writes.
"""
import os,io,base64,posixpath,json,gzip,hashlib,re,paramiko
keydata=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode()
key=None
for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
 try:key=cls.from_private_key(io.StringIO(keydata));break
 except Exception:pass
if not key:raise RuntimeError('Configured SFTP key not usable')
ssh=paramiko.SSHClient()
ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=os.environ['SFTP_HOST'],port=int(os.environ.get('SFTP_PORT') or 22),username=os.environ['SFTP_USERNAME'],pkey=key,look_for_keys=False,allow_agent=False,timeout=12)
ftp=ssh.open_sftp()
root=os.environ['SFTP_ROOT'].replace('\\','/').rstrip('/')
if root.endswith('/sps/spr'):root=root[:-4]
elif root.endswith('/public_html'):root+='/sps'
if not root.endswith('/sps'):raise RuntimeError('unexpected web root')
def read(path):
 with ftp.open(posixpath.join(root,path),'rb') as f:return f.read()
try:
 js=read('script.js').decode('utf-8')
 print('[862B JS SHA]',hashlib.sha256(js.encode()).hexdigest()[:16],flush=True)
 for marker in ['function renderCard(r){','verifiedThroughRunDestination','const destination=normaliseDisplayLocation','Trip Destination','tripDestination','tripDest','destinationTiming','function renderShiftCard(shift){']:
  ids=[m.start() for m in re.finditer(re.escape(marker),js)]
  print('[862B SCRIPT MARKER]',marker,len(ids),flush=True)
  if ids and marker in ('function renderCard(r){','const destination=normaliseDisplayLocation','Trip Destination','tripDestination','destinationTiming'):
   for i in ids[:2]:
    print('[862B SCRIPT]',marker,js[max(0,i-600):i+1450].replace('\n','\\n')[:2200],flush=True)
 try:
  data=read('spr/i/d/2026-11-01.json.gz')
 except Exception as ex:
  print('[862B INDEX LOOKUP ERROR]',type(ex).__name__,str(ex)[:160],flush=True)
  for p in ('spr/i/d','spr/i'):
   try:print('[862B INDEX LIST]',p,ftp.listdir(posixpath.join(root,p))[-25:],flush=True)
   except Exception as x:print('[862B INDEX LIST ERROR]',p,str(x)[:100],flush=True)
 else:
  obj=json.loads(gzip.decompress(data))
  print('[862B INDEX META]',{k:obj.get(k) for k in ('date','role','parserBuild','pageLayoutBuild')},'pages',len(obj.get('pages',[])),'records',len(obj.get('records',[])),flush=True)
  for r in [x for x in obj.get('records',[]) if str(x.get('run','')).upper()=='862B'][:10]:
   fields=('run','crewShift','crew','page','_index','runStartTime','runEndTime','runDestination','declaredDestination','tripDestination','originTiming','destinationTiming','formsRun','nextDuty','outgoingRelieveShift','outgoingRelieveLocation','incomingRelieveShift','incomingRelieveLocation','timetableRows','formsChain')
   short={}
   for k in fields:
    v=r.get(k)
    if k=='timetableRows':v=(v or [])[-6:]
    if k=='formsChain':v=(v or [])[:2]
    if v is not None:short[k]=v
   print('[862B RECORD]',json.dumps(short,ensure_ascii=False)[:6000],flush=True)
  print('[862B RECORD COUNT]',len([r for r in obj.get('records',[]) if str(r.get('run','')).upper()=='862B']),flush=True)
finally:
 ftp.close();ssh.close()
