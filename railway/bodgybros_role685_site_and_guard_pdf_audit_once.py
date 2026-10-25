#!/usr/bin/env python3
"""Build 685: keep selected Drivers/Guards SPR records isolated.

Deploy only guarded minimal fixes to Build 684 site script.js:
- Reject stale/mislabeled cross-role cached and published SPR indexes
- Skip device-cache auto-restore in Railway's indexer browser
- Refuse search while role/date selector differs from loaded SPR
- Do not change Shift PDF extraction/caching, roster UI, PDF rendering, etc.
All SFTP writes checksum-verified with offline JS syntax check.
"""
import os,io,base64,posixpath,hashlib,tempfile,subprocess,re
from pathlib import Path
import paramiko
MARKER='// SPR_ROLE_ISOLATION_685'
HELPERS=r'''// Build 685: detect a wrong-role index using the original printed SPR headings.
// The file name/metadata alone is insufficient: a Guards index was published
// with Driver pages while labelled "guard".
function sprPagesMatchRole(pages,role){
  if(!Array.isArray(pages)||!['driver','guard'].includes(role))return false;
  const seen={driver:0,guard:0};
  for(const page of pages.slice(0,18)){
    const header=String(page?.text||'').slice(0,300);
    const match=header.match(/\bSydney\s+Trains?\s+(Driver|Guard)\b/i);
    if(match)seen[match[1].toLowerCase()]++;
  }
  // Fail closed when the index contains a clear contradictory heading.
  // Ignore pages with no recognised heading to preserve legacy SPR formats.
  return !(seen[role==='guard'?'driver':'guard']>0);
}
'''
def one(s,a,b,label):
 n=s.count(a)
 if n!=1:raise RuntimeError(f'Expected Build684 {label} anchor once, got {n}; website unchanged')
 return s.replace(a,b,1)
def patch(source):
 if MARKER in source:return source,False
 if 'SPR_RESTORED_SHIFT_LOADER_684' not in source or 'SPR_BUILD683_RESTORED_650_FAST_SHIFT_CACHE' not in source:
  raise RuntimeError('Expected working Build 684 Shift loader marker missing')
 if 'function sprPagesMatchRole(' in source:raise RuntimeError('Conflicting existing page-role validator')
 source=one(source,'async function loadPublishedSprIndex(date,role){',HELPERS+'\nasync function loadPublishedSprIndex(date,role){','role helper insert')
 anchor='''  return index;
}
async function publishedIndexSha(date,role){'''
 updated='''  if(!sprPagesMatchRole(index.pages,role)){
    throw new Error('Published '+role+' SPR index contains pages for the other crew role');
  }
  return index;
}
async function publishedIndexSha(date,role){'''
 source=one(source,anchor,updated,'published index guard')
 anchor='''  if(!cached||!Array.isArray(cached.pages)||!cached.pages.length)return false;
  try{'''
 updated='''  if(!cached||!Array.isArray(cached.pages)||!cached.pages.length)return false;
  // The device may still retain an old mislabelled Guards index.
  if(!sprPagesMatchRole(cached.pages,cached.role)){
    console.warn('Ignoring cached SPR index with incorrect role',cached.date,cached.role);
    if(cached.date&&cached.role)await deleteRetainedSpr(cached.date,cached.role);
    return false;
  }
  try{'''
 source=one(source,anchor,updated,'device cache role check')
 anchor='''function scheduleRetainedSprRestore(){
  const run=()=>restoreRetainedSpr().catch(error=>console.warn('Retained SPR restore failed',error));'''
 updated='''function scheduleRetainedSprRestore(){
  // The headless Railway indexer must NEVER restore the previous Driver
  // index over a newly requested Guard source PDF.
  if(window.__SPR_PREINDEX_MODE || new URLSearchParams(location.search).has('spr_preindex'))return;
  const run=()=>restoreRetainedSpr().catch(error=>console.warn('Retained SPR restore failed',error));'''
 source=one(source,anchor,updated,'indexer cache restore bypass')
 anchor='''function search(value){
  if(ui.type.value==='name')return searchName(value);'''
 updated='''function search(value){
  // The dropdown selection is not the loaded document until Load is clicked.
  // Never show Driver results when the user has switched the selector to Guard.
  if(state.pages.length && (ui.role.value!==state.role || ui.date.value!==state.loadedDate)){
    ui.results.replaceChildren();
    setStatus('Selected '+ui.role.value+' SPR is not loaded yet. Click Load to search that date and role.','warning');
    return;
  }
  if(ui.type.value==='name')return searchName(value);'''
 source=one(source,anchor,updated,'search role selection consistency')
 anchor='''      const data={version:SPR_RETAIN_VERSION,parserBuild:SPR_PARSER_BUILD,pageLayoutBuild:SPR_PAGE_LAYOUT_BUILD,
        date,role,fileName:state.fileName,pages:state.pages,records:state.records,shifts:state.shifts};'''
 updated='''      if(!sprPagesMatchRole(state.pages,role))throw new Error('Source '+role+' PDF contains headings for the other SPR role');
      const data={version:SPR_RETAIN_VERSION,parserBuild:SPR_PARSER_BUILD,pageLayoutBuild:SPR_PAGE_LAYOUT_BUILD,
        date,role,fileName:state.fileName,pages:state.pages,records:state.records,shifts:state.shifts};'''
 source=one(source,anchor,updated,'indexer source role validation')
 # When raw source PDF loads after invalid cached/published index, verify too.
 anchor='''    setProcessingProgress('Interpreting runs…',92);'''
 updated='''    if(!sprPagesMatchRole(state.pages,state.role))
      throw new Error('Loaded '+state.role+' SPR PDF contains pages for the other crew role');
    setProcessingProgress('Interpreting runs…',92);'''
 source=one(source,anchor,updated,'source PDF role validation')
 return MARKER+'\n'+source,True
def sha(b):return hashlib.sha256(b).hexdigest()
def read(sftp,p):
 with sftp.open(p,'rb') as f:return f.read()
def remote_write(sftp,p,old,data):
 if sha(read(sftp,p))!=sha(old):raise RuntimeError('Live website changed concurrently: '+posixpath.basename(p))
 stage=p+'.role685'
 try:
  with sftp.open(stage,'wb') as f:f.write(data)
  if sha(read(sftp,stage))!=sha(data):raise RuntimeError('Unverified SFTP temp file')
  sftp.posix_rename(stage,p)
  if sha(read(sftp,p))!=sha(data):raise RuntimeError('Unverified final SFTP file')
 finally:
  try:sftp.remove(stage)
  except Exception:pass
def main():
 e=os.environ
 for name in ('SFTP_HOST','SFTP_USERNAME','SFTP_PRIVATE_KEY_B64','SFTP_ROOT'):
  if not e.get(name):raise RuntimeError('Primary Bodgybros SFTP variable missing: '+name)
 root=posixpath.normpath(e['SFTP_ROOT'].replace('\\','/'))
 if root.endswith('/sps/spr/d') or root.endswith('/sps/spr/g'):root=posixpath.dirname(posixpath.dirname(posixpath.dirname(root)))
 elif root.endswith('/sps/spr'):root=posixpath.dirname(root)
 elif root.endswith('/public_html'):root=posixpath.join(root,'sps')
 if not root.endswith('/sps'):raise RuntimeError('Unexpected website /sps path')
 priv=base64.b64decode(e['SFTP_PRIVATE_KEY_B64']).decode()
 key=None
 for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
  try:key=cls.from_private_key(io.StringIO(priv));break
  except Exception:pass
 if key is None:raise RuntimeError('SFTP key not recognized')
 ssh=paramiko.SSHClient()
 ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
 ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
 try:
  ssh.connect(hostname=e['SFTP_HOST'],port=int(e.get('SFTP_PORT') or 22),
    username=e['SFTP_USERNAME'],pkey=key,timeout=12,
    auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
  with ssh.open_sftp() as sftp:
   p=posixpath.join(root,'script.js')
   old=read(sftp,p)
   print('[GUARD SOURCE AUDIT] Live Build685 JS read, checking Guard source PDF',flush=True)
   for needle in ('window.__SPR_INDEXER_API','async function loadOnlinePdf(){'):
    at=old.decode('utf-8').find(needle)
    if at>=0:
     snippet=' '.join(old.decode('utf-8')[at:at+850].split())
     print('[GUARD SCRIPT AUDIT] '+needle+' '+snippet[:850],flush=True)
   from pypdf import PdfReader
   pdfpath=posixpath.join(root,'spr/g/All Guards Combined 26_10_2026.pdf')
   size=sftp.stat(pdfpath).st_size
   print('[GUARD SOURCE AUDIT] Guard PDF remote bytes='+str(size),flush=True)
   with sftp.open(pdfpath,'rb') as source:
    source.prefetch(file_size=size,max_concurrent_requests=12)
    data=source.read()
   print('[GUARD SOURCE AUDIT] Guard PDF downloaded='+str(len(data))+' SHA256-prefix='+sha(data)[:16],flush=True)
   document=PdfReader(io.BytesIO(data),strict=False)
   print('[GUARD SOURCE AUDIT] Guard PDF pages='+str(len(document.pages)),flush=True)
   for i in (0,1,2,20):
    if i>=len(document.pages):continue
    txt=(document.pages[i].extract_text() or '')[:1700]
    headings=re.findall(r'Sydney\s+Trains?\s+(Driver|Guard)\b',txt,re.I)
    print('[GUARD SOURCE AUDIT] PDF page '+str(i+1)+' headings='+str(headings[:3])+' hasDriver='+str(bool(re.search(r'\bDriver\b',txt,re.I)))+' hasGuard='+str(bool(re.search(r'\bGuard\b',txt,re.I))),flush=True)
   output,changed=patch(old.decode('utf-8'))
   if not changed:
    print('[685 WEBSITE] role checks already installed',flush=True);return
   fd,tmp=tempfile.mkstemp(suffix='.js')
   try:
    with os.fdopen(fd,'w',encoding='utf8') as f:f.write(output)
    check=subprocess.run(['node','--check',tmp],capture_output=True,text=True,timeout=20)
    if check.returncode:raise RuntimeError('Patched JS failed syntax check: '+check.stderr[:280])
   finally:
    try:os.unlink(tmp)
    except OSError:pass
   changes=[(p,old,output.encode())]
   for name in ('index.html','index.php'):
    fpath=posixpath.join(root,name);orig=read(sftp,fpath);html=orig.decode()
    html=one(html,'./script.js?v=684','./script.js?v=685',name+' cache key')
    html=re.sub(r'(class=["\']build-number["\']>Build )684\b',r'\g<1>685',html,count=1)
    changes.append((fpath,orig,html.encode()))
   backup=Path('/data/website-build685-backups');backup.mkdir(parents=True,exist_ok=True)
   for path,orig,_ in changes:(backup/posixpath.basename(path)).write_bytes(orig)
   for path,old,new in changes:
    remote_write(sftp,path,old,new)
    print('[685 WEBSITE VERIFIED] '+posixpath.basename(path)+' sha='+sha(new)[:14],flush=True)
   print('[685 WEBSITE READY] Driver/Guard indexes and device caches validated; Build684 shift extraction unchanged',flush=True)
 finally:ssh.close()
if __name__=='__main__':main()
