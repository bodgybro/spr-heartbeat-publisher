#!/usr/bin/env python3
"""Build 678: precisely restore pre-677 Bodgybros shift-PDF prefetch and caching.
Only edit the five 677 regressions. Keep the viewer timeout and backup link.
Safety: accept only exact expected live code; preserve existing PDFs, rosters,
indices and parser. Record original source backups and remote SHA-256 proofs.
"""
import os,io,base64,posixpath,hashlib,re
from pathlib import Path
import paramiko

def once(t,a,b,label):
    n=t.count(a)
    if n!=1:raise RuntimeError(f'Expected Build 677 marker {label} once; got {n}; no files changed')
    return t.replace(a,b,1)

def patch_script(t):
    if '// SPR_BODGYBROS_RESTORE_FAST_SHIFT_678' in t:return t,False
    if '// SPR_BODGYBROS_INDEXED_SHIFT_677' not in t:
        raise RuntimeError('Build 677 website marker missing; refusing to patch unexpected frontend')
    t=once(t,
      """  // Build 677: the published index already gives each shift's exact source-page numbers.
  // Don't flood the network or block a click by prefetching an 800+ page PDF.
  if(!window.__SPR_PREINDEX_MODE)return;""",
      """  // Restore working Bodgybros background original-PDF prefetch.
  if(isKustomSprHost()&&!window.__SPR_PREINDEX_MODE)return;""",
      'background PDF download')
    t=once(t,
      """    // Build 677: no whole-document/prewarm extraction on the shift click path.""",
      """    if(isKustomSprHost())warmSecondaryShiftSource();
    else scheduleVisibleShiftPdfPrewarm();""",
      'prewarm after downloaded PDF')
    t=once(t,
      """    // Prefer source URL range requests even if a background download completed.
    // Copying 10-20MB into pdf-lib used to monopolise the first shift click.
    const liveUrl=state.sourceUrl&&!state.sourceUrl.startsWith('blob:');
    const task=liveUrl
      ? pdfjsLib.getDocument({url:new URL(state.sourceUrl,document.baseURI).href,
          rangeChunkSize:262144,disableStream:true,disableAutoFetch:true,
          withCredentials:false})
      : pdfjsLib.getDocument({data:new Uint8Array(state.pdfBytes.slice(0))});""",
      """    const task=state.pdfBytes
      ? pdfjsLib.getDocument({data:new Uint8Array(state.pdfBytes.slice(0))})
      : pdfjsLib.getDocument({url:new URL(state.sourceUrl,document.baseURI).href,
          rangeChunkSize:262144,disableStream:true,disableAutoFetch:true,
          withCredentials:false});""",
      'pre-677 PDF source selection')
    t=once(t,
      """    if(state.sourceUrl||state.pdfDoc){
      // Build 677: on Bodgybros and any other host, the prepared index supplies
      // exact page numbers. Render only those pages; never parse all 800+ pages
      // through pdf-lib merely to open one shift.""",
      """    if(isKustomSprHost()&&state.sourceUrl){
      // Use range-based page rendering only on the other site's legacy path.
      // Bodgybros uses the cached, text-preserving original PDF page extraction.""",
      'text-preserving shift extraction')
    t=once(t,
      """function scheduleVisibleShiftPdfPrewarm(){
  // Build 677: no speculative extraction. It can hold a PDF loading promise
  // and starve the first *user-requested* shift. Indexed pages open on click.
  return;""",
      """function scheduleVisibleShiftPdfPrewarm(){""",
      'restore idle shift extraction')
    t='// SPR_BODGYBROS_RESTORE_FAST_SHIFT_678\n'+t
    if "Shift page extraction exceeded 45 seconds" not in t:
        raise RuntimeError('Viewer timeout protection missing')
    if "scheduleVisibleShiftPdfPrewarm();\n    return buffer;" not in t:
        raise RuntimeError('Restored PDF prewarm path is not connected')
    if "if(isKustomSprHost()&&state.sourceUrl){" not in t:
        raise RuntimeError('Expected shift extraction branch missing')
    return t,True

def digest(data):return hashlib.sha256(data).hexdigest()
def read(sftp,path):
    with sftp.open(path,'rb') as f:return f.read()
def website_root(raw):
    r=posixpath.normpath(raw.strip().replace('\\','/'))
    if r.endswith('/sps'):return r
    if r.endswith('/sps/spr'):return posixpath.dirname(r)
    if r.endswith('/sps/spr/d') or r.endswith('/sps/spr/g'):
        return posixpath.dirname(posixpath.dirname(posixpath.dirname(r)))
    if r.endswith('/public_html'):return posixpath.join(r,'sps')
    raise RuntimeError('Unknown Bodgybros SFTP_ROOT layout, refusing to write')

def write_checked(sftp,path,original,new):
    if digest(read(sftp,path))!=digest(original):
        raise RuntimeError('Remote file changed concurrently: '+posixpath.basename(path))
    if original==new:return
    tmp=path+'.build678-pending'
    try:
        with sftp.open(tmp,'wb') as f:f.write(new)
        if digest(read(sftp,tmp))!=digest(new):raise RuntimeError('Temporary remote SHA mismatch')
        sftp.posix_rename(tmp,path)
        if digest(read(sftp,path))!=digest(new):raise RuntimeError('Final remote SHA mismatch')
    finally:
        try:sftp.remove(tmp)
        except Exception:pass

def main():
    for name in ('SFTP_HOST','SFTP_USERNAME','SFTP_PRIVATE_KEY_B64','SFTP_ROOT'):
        if not os.environ.get(name):raise RuntimeError('Missing '+name+', website not changed')
    root=website_root(os.environ['SFTP_ROOT'])
    keytext=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=typ.from_private_key(io.StringIO(keytext));break
        except Exception:pass
    if key is None:raise RuntimeError('Existing SFTP private key not supported')
    kh=Path('/data/credentials/spr-sftp-known_hosts')
    if not kh.exists():raise RuntimeError('Bodgybros SFTP known hosts missing')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(kh))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=os.environ['SFTP_HOST'],port=int(os.environ.get('SFTP_PORT') or 22),
            username=os.environ['SFTP_USERNAME'],pkey=key,timeout=10,
            auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
        with ssh.open_sftp() as sftp:
            js=posixpath.join(root,'script.js')
            raw=read(sftp,js)
            updated,changed=patch_script(raw.decode('utf-8'))
            if not changed:
                print('[BUILD 678] Fast shift PDF caching already installed; no changes',flush=True)
                return
            files=[(js,raw,updated.encode('utf-8'))]
            for name in ('index.php','index.html'):
                path=posixpath.join(root,name)
                old=read(sftp,path)
                doc=old.decode('utf-8')
                doc=once(doc,'./script.js?v=677','./script.js?v=678',name+' JS cache version')
                doc=re.sub(r'(class=["\']build-number["\']>Build )677\b',r'\g<1>678',doc)
                files.append((path,old,doc.encode('utf-8')))
            backup=Path('/data/website-build678-backups')
            backup.mkdir(parents=True,exist_ok=True)
            for path,old,_ in files:
                (backup/posixpath.basename(path)).write_bytes(old)
            for path,old,new in files:
                write_checked(sftp,path,old,new)
                print('[BUILD 678 RESTORED] '+posixpath.basename(path)+' SHA-256 '+digest(new)[:12],flush=True)
    finally:ssh.close()
if __name__=='__main__':main()
