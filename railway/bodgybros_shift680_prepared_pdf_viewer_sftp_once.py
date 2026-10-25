#!/usr/bin/env python3
"""Build 680: prefer pre-extracted original PDF pages on Bodgybros."""
import os,base64,io,posixpath,hashlib,re
from pathlib import Path
import paramiko

MARKER='// SPR_PREEXTRACTED_ORIGINAL_SHIFT_PDF_680'
HELPER=r'''
// Railway has already copied the indexed ORIGINAL pages into separate PDFs.
// A SHA-256 source-bound manifest prevents serving a stale extraction.
let shiftCacheManifestKey='';
let shiftCacheManifestPromise=null;
async function getPreparedShiftManifest(){
  const date=String(state.loadedDate||'');
  const role=state.role==='guard'?'g':'d';
  const sha=String(state.sourceSha||'').toLowerCase();
  if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||!/^[a-f0-9]{64}$/.test(sha))return null;
  const key=date+'|'+role+'|'+sha;
  if(shiftCacheManifestKey!==key){
    shiftCacheManifestKey=key;
    shiftCacheManifestPromise=null;
  }
  if(!shiftCacheManifestPromise){
    shiftCacheManifestPromise=(async()=>{
      const controller=new AbortController();
      const timer=setTimeout(()=>controller.abort(),4500);
      try{
        const url='./spr/x/'+role+'/'+date+'/manifest.json';
        const response=await fetch(url,{cache:'no-store',credentials:'same-origin',signal:controller.signal});
        if(!response.ok)return null;
        const manifest=await response.json();
        if(manifest?.version!==680||manifest?.date!==date||
          manifest?.role!==role||String(manifest?.sourceSha||'').toLowerCase()!==sha||
          !Array.isArray(manifest.shifts))return null;
        return manifest;
      }finally{clearTimeout(timer)}
    })().catch(error=>{console.debug('Prepared shift cache unavailable',error);return null});
  }
  const manifest=await shiftCacheManifestPromise;
  // Keep checking while background extraction is building more shift PDFs.
  if(!manifest||!manifest.complete)shiftCacheManifestPromise=null;
  return manifest;
}
async function getPreparedShiftPdf(shift){
  const manifest=await getPreparedShiftManifest();
  if(!manifest||!manifest.shifts.includes(shift))return '';
  return './spr/x/'+manifest.role+'/'+manifest.date+'/'+encodeURIComponent(shift)+'.pdf';
}
'''
def patch(js):
    if MARKER in js:return js,False
    if 'extracted.copyPages(source,pages.map(page=>page-1))' not in js:
        raise RuntimeError('Existing original-page copyPages fallback missing')
    anchor='async function handleShiftSprClick(event){'
    old='''  try{
    // A failed PDF worker or remote range request must not leave a blank'''
    new='''  try{
    // No browser-side 800-page parse: open the pre-extracted source PDF pages.
    const prepared=await getPreparedShiftPdf(shift);
    if(prepared){
      viewer.location.replace(new URL(prepared,document.baseURI).href+'#page=1&zoom=page-width');
      setStatus('Opened '+pages.length+' original SPR page'+(pages.length===1?'':'s')+
        ' for Shift '+shift+' from the prepared shift PDF.','success');
      return;
    }
    // A failed PDF worker or remote range request must not leave a blank'''
    if js.count(anchor)!=1 or js.count(old)!=1:
        raise RuntimeError('Unexpected Shift handler anchor; no overwrite')
    js=MARKER+'\n'+js.replace(anchor,HELPER+'\n'+anchor,1).replace(old,new,1)
    if js.count('const prepared=await getPreparedShiftPdf(shift);')!=1:
        raise RuntimeError('Prepared shift URL call unexpectedly duplicated')
    return js,True

def h(data):return hashlib.sha256(data).hexdigest()
def read(sftp,p):
    with sftp.open(p,'rb') as f:return f.read()
def root_path(raw):
    p=posixpath.normpath(raw.strip().replace('\\','/'))
    if p.endswith('/sps'):return p
    if p.endswith('/sps/spr'):return posixpath.dirname(p)
    if p.endswith('/sps/spr/d') or p.endswith('/sps/spr/g'):
        return posixpath.dirname(posixpath.dirname(posixpath.dirname(p)))
    if p.endswith('/public_html'):return posixpath.join(p,'sps')
    raise RuntimeError('Unknown Bodgybros SFTP root')
def remote_put(sftp,path,old,new):
    if h(read(sftp,path))!=h(old):
        raise RuntimeError('Website changed concurrently: '+posixpath.basename(path))
    tmp=path+'.shift680-updating'
    try:
        with sftp.open(tmp,'wb') as out:out.write(new)
        if h(read(sftp,tmp))!=h(new):raise RuntimeError('Unverified SFTP temporary file')
        sftp.posix_rename(tmp,path)
        if h(read(sftp,path))!=h(new):raise RuntimeError('Unverified SFTP final file')
    finally:
        try:sftp.remove(tmp)
        except Exception:pass

def main():
    for key in ('SFTP_HOST','SFTP_USERNAME','SFTP_PRIVATE_KEY_B64','SFTP_ROOT'):
        if not os.environ.get(key):raise RuntimeError('Existing Bodgybros SFTP config missing: '+key)
    known=Path('/data/credentials/spr-sftp-known_hosts')
    if not known.exists():raise RuntimeError('Bodgybros known host key not available')
    key_data=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    private=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:private=cls.from_private_key(io.StringIO(key_data));break
        except Exception:pass
    if private is None:raise RuntimeError('Invalid Bodgybros SFTP key')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(known))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=os.environ['SFTP_HOST'],port=int(os.environ.get('SFTP_PORT') or 22),
            username=os.environ['SFTP_USERNAME'],pkey=private,
            timeout=10,auth_timeout=12,banner_timeout=12,
            allow_agent=False,look_for_keys=False)
        with ssh.open_sftp() as sftp:
            base=root_path(os.environ['SFTP_ROOT'])
            js_path=posixpath.join(base,'script.js')
            old=read(sftp,js_path)
            updated,changed=patch(old.decode('utf-8'))
            if not changed:
                print('[BUILD 680 WEBSITE] Already patched',flush=True)
                return
            files=[(js_path,old,updated.encode('utf-8'))]
            for name in ('index.php','index.html'):
                path=posixpath.join(base,name)
                old_html=read(sftp,path)
                html=old_html.decode('utf-8')
                if html.count('./script.js?v=679')!=1:
                    raise RuntimeError(name+' JS cache version differs from Build 679')
                html=html.replace('./script.js?v=679','./script.js?v=680',1)
                html=re.sub(r'(class=["\']build-number["\']>Build )679\b',r'\g<1>680',html,count=1)
                files.append((path,old_html,html.encode('utf-8')))
            backups=Path('/data/website-build680-backups')
            backups.mkdir(parents=True,exist_ok=True)
            for path,original,_ in files:(backups/posixpath.basename(path)).write_bytes(original)
            for path,original,output in files:
                remote_put(sftp,path,original,output)
                print('[BUILD 680 WEBSITE VERIFIED] '+posixpath.basename(path)+' '+h(output)[:14],flush=True)
    finally:ssh.close()
if __name__=='__main__':main()
