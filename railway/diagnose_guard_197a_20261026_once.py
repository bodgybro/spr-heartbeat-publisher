#!/usr/bin/env python3
"""Read-only Build 684 diagnostic: which 26/10 index/search contains run 197A?
Never print crew names, credentials, cookies, complete PDF text, or source files.
"""
import os, io, base64, posixpath, re, json, gzip, hashlib, time
from pathlib import Path
import paramiko
def read(sftp,remote):
 with sftp.open(remote,'rb') as f:
  length=sftp.stat(remote).st_size
  if length>2_000_000:f.prefetch(file_size=length,max_concurrent_requests=16)
  return f.read()
def main():
 e=os.environ; private=base64.b64decode(e['SFTP_PRIVATE_KEY_B64']).decode()
 key=None
 for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
  try:key=cls.from_private_key(io.StringIO(private));break
  except Exception:pass
 if key is None:raise RuntimeError('SFTP key unavailable')
 root=posixpath.normpath(e['SFTP_ROOT'].replace('\\','/'))
 if root.endswith('/sps/spr/d') or root.endswith('/sps/spr/g'):root=posixpath.dirname(posixpath.dirname(posixpath.dirname(root)))
 elif root.endswith('/sps/spr'):root=posixpath.dirname(root)
 elif root.endswith('/public_html'):root=posixpath.join(root,'sps')
 if not root.endswith('/sps'):raise RuntimeError('Unexpected site path')
 ssh=paramiko.SSHClient()
 ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
 ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
 try:
  ssh.connect(hostname=e['SFTP_HOST'],port=int(e.get('SFTP_PORT') or 22),
    username=e['SFTP_USERNAME'],pkey=key,timeout=10,auth_timeout=10,banner_timeout=10,allow_agent=False,look_for_keys=False)
  with ssh.open_sftp() as sftp:
   for role in ('d','g'):
    date='2026-10-26'
    path=posixpath.join(root,'spr/i',role,date+'.json.gz')
    meta_path=posixpath.join(root,'spr/i',role,date+'.meta.json')
    data=gzip.decompress(read(sftp,path))
    o=json.loads(data)
    meta=json.loads(read(sftp,meta_path))
    lines=[p.get('text','')[:260] for p in o.get('pages',[])[:3] if isinstance(p,dict)]
    page_type=['guard' if re.search(r'Sydney Trains?\s+Guard\b',t,re.I) else 'driver' if re.search(r'Sydney Trains?\s+Driver\b',t,re.I) else 'unknown' for t in lines]
    rec=[r for r in o.get('records',[]) if isinstance(r,dict) and str(r.get('run','')).strip().replace('-','').upper()=='197A']
    shifts=[str(r.get('crewShift') or '') for r in rec[:6]]
    pages=[int(r.get('page') or 0) for r in rec[:6]]
    print('[ROLE CHECK] '+role+' index role='+str(o.get('role'))+
          ' metaRole='+str(meta.get('role'))+
          ' pdfSha='+str(meta.get('sourceSha',''))[-12:]+
          ' pages='+str(len(o.get('pages') or []))+
          ' records='+str(len(o.get('records') or []))+
          ' matching197A='+str(len(rec))+
          ' crewShiftIDs='+repr(shifts)+
          ' matchedPages='+repr(pages)+
          ' sampledPageTypes='+repr(page_type),flush=True)
    matching=[p for p in o.get('pages',[]) if any(str(p.get('pageNo'))==str(q) for q in pages)]
    role_samples=['guard' if re.search('Sydney Trains? Guard',str(p.get('text',''))[:500],re.I) else 'driver' if re.search('Sydney Trains? Driver',str(p.get('text',''))[:500],re.I) else 'unknown' for p in matching[:6]]
    print('[ROLE CHECK] '+role+' run197A matching page types '+repr(role_samples),flush=True)
   js=read(sftp,posixpath.join(root,'script.js')).decode()
   print('[ROLE CHECK] site current Build684 marker='+str('SPR_RESTORED_SHIFT_LOADER_684' in js)+
    ' guard-role-cache-key='+str("retainedSprKey(date,role)" in js)+
    ' run-search-role-filter='+str("state.role==='guard'" in js[js.find('function searchRun('):js.find('function searchName(')]),flush=True)
 except Exception as err:
  print('[ROLE CHECK ERROR] '+type(err).__name__+' '+str(err)[:160],flush=True)
  raise
 finally:ssh.close()
if __name__=='__main__':main()
