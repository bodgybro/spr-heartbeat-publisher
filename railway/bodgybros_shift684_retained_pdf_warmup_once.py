#!/usr/bin/env python3
"""Build 684: fix restored original SPR PDF shift links, using Build 650.

- Retained device and indexed-select paths begin pdf-lib parsing immediately.
- Original PDF bytes persist and are reused for all shifts.
- Extract only original pages (copyPages); no image rendering.
- A stale retained byte buffer is refreshed once automatically if parsing fails.
- Remove the arbitrary 45s timeout introduced after the working Build 650.
- Leave roster updates, parsing, indexes, SPR upload logic untouched.
Guard the exact current Build 683; verify patched JS syntax before SFTP writes.
"""
import os,io,base64,posixpath,hashlib,re,tempfile,subprocess
from pathlib import Path
import paramiko

MARK='// SPR_RESTORED_SHIFT_LOADER_684'
WARM=r'''let shiftSourceWarmEpoch=-1;
let shiftSourceWarmPromise=null;
function showShiftPdfReady(){
  if(!state.pdfBytes||!state.pages.length||!state.pdfLibPromise)return;
  const suffix=' · Original Shift PDFs ready';
  if(!ui.summary.textContent.includes(suffix))ui.summary.textContent+=suffix;
}
function scheduleShiftPdfWarmParse(){
  if(!state.pdfBytes||!state.pages.length||window.__SPR_PREINDEX_MODE)return;
  const epoch=activePdfSelectionEpoch;
  // Reuse the same in-flight parser on a restored SPR, new Load, or results.
  if(shiftSourceWarmEpoch===epoch && shiftSourceWarmPromise)return shiftSourceWarmPromise;
  shiftSourceWarmEpoch=epoch;
  const bytes=state.pdfBytes;
  const start=(async()=>{
    try{
      await ensurePdfLibraries();
      if(epoch!==activePdfSelectionEpoch || state.pdfBytes!==bytes)return;
      if(!state.pdfLibPromise)state.pdfLibPromise=PDFDocument.load(bytes,{updateMetadata:false});
      const document=await state.pdfLibPromise;
      if(!document||epoch!==activePdfSelectionEpoch||state.pdfBytes!==bytes)return;
      showShiftPdfReady();
      scheduleVisibleShiftPdfPrewarm();
    }catch(error){
      if(epoch===activePdfSelectionEpoch&&state.pdfBytes===bytes){
        console.warn('Original SPR cached PDF is not prepared:',error);
        state.pdfLibPromise=null;
        shiftSourceWarmEpoch=-1;
        // Searches remain usable; a click can retry from the actual PDF.
        if(ui.summary.textContent.includes('Original Shift PDFs ready'))
          ui.summary.textContent=ui.summary.textContent.replace(' · Original Shift PDFs ready','');
      }
    }
  })();
  shiftSourceWarmPromise=start;
  return start;
}
'''
PREPARE=r'''async function prepareShiftPdfUrl(shift,onProgress=()=>{}){
  const value=normaliseRun(shift||'');
  if(!value||!state.pages.length)return '';
  const ready=state.shiftPdfUrls.get(value);
  if(ready)return ready;
  const pending=state.shiftPdfPromises.get(value);
  if(pending)return pending;
  const pages=[...new Set(state.shiftPages.get(value)||[])].sort((a,b)=>a-b);
  if(!pages.length)return '';
  const epoch=activePdfSelectionEpoch;
  const originalDate=state.loadedDate;
  const originalRole=state.role;
  const urlCache=state.shiftPdfUrls;
  const pendingCache=state.shiftPdfPromises;
  const sameSelection=()=> {
    if(epoch!==activePdfSelectionEpoch || state.loadedDate!==originalDate || state.role!==originalRole)
      throw new DOMException('SPR selection changed','AbortError');
  };
  const extract=async()=>{
    sameSelection();
    if(!state.pdfBytes){
      onProgress('Downloading original SPR once for Shift '+value+'…');
      await ensureActivePdfBytes();
    }
    sameSelection();
    await ensurePdfLibraries();
    sameSelection();
    // Build 650: parse the source document ONCE, then copy the selected
    // ORIGINAL PDF pages. Never render images or scan the complete PDF per click.
    if(!state.pdfLibPromise)state.pdfLibPromise=PDFDocument.load(state.pdfBytes,{updateMetadata:false});
    const source=await state.pdfLibPromise;
    sameSelection();
    const extracted=await PDFDocument.create();
    const originals=await extracted.copyPages(source,pages.map(p=>p-1));
    originals.forEach(page=>extracted.addPage(page));
    const bytes=await extracted.save({useObjectStreams:false,addDefaultPage:false});
    sameSelection();
    const url=URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));
    urlCache.set(value,url);
    return url;
  };
  const job=(async()=>{
    try{return await extract()}
    catch(error){
      if(error?.name==='AbortError')throw error;
      // Cached PDF may be stale/damaged even when its search index looks
      // correct. A manual Load previously fixed this; now do that once
      // automatically, without resetting search results or indexes.
      if(!state.pdfBytes||!originalDate)throw error;
      // A blob URL from a previous tab is never valid after a device restore.
      if(!state.sourceUrl||String(state.sourceUrl).startsWith('blob:')){
        const [year,month,day]=originalDate.split('-');
        const driver=originalRole==='driver';
        state.sourceUrl='./spr/'+(driver?'d':'g')+'/All%20'+
          (driver?'Drivers':'Guards')+'%20Combined%20'+day+'_'+month+'_'+year+'.pdf';
      }
      console.warn('Shift '+value+' cached source failed, retrying original PDF once:',error);
      sameSelection();
      state.pdfBytes=null;
      state.pdfLibPromise=null;
      shiftSourceWarmEpoch=-1;
      shiftSourceWarmPromise=null;
      onProgress('Refreshing original SPR PDF once for Shift '+value+'…');
      await ensureActivePdfBytes();
      sameSelection();
      return await extract();
    }
  })();
  pendingCache.set(value,job);
  try{return await job}
  finally{if(pendingCache.get(value)===job)pendingCache.delete(value)}
}'''

CLICK=r'''async function handleShiftSprClick(event){
  const link=event.target.closest('.shift-spr-link');
  if(!link)return;
  event.preventDefault();
  const shift=normaliseRun(link.dataset.shift||'');
  const pages=[...new Set(state.shiftPages.get(shift)||[])].sort((a,b)=>a-b);
  if(!pages.length||(!state.pdfBytes&&!state.sourceUrl)){
    setStatus('Original SPR pages for Shift '+shift+' were not identified.','warning');
    return;
  }
  const viewer=window.open('about:blank','_blank');
  if(!viewer){setStatus('Allow pop-ups to open the original Shift PDFs.','warning');return}
  viewer.document.title='Shift '+shift;
  const cached=state.shiftPdfUrls.get(shift);
  if(cached){
    viewer.location.replace(cached+'#page=1&zoom=page-width');
    return;
  }
  viewer.document.body.textContent=state.pdfBytes
    ?'Extracting '+pages.length+' original PDF page(s) for Shift '+shift+'…'
    :'Downloading the original SPR PDF once for Shift '+shift+'…';
  try{
    // Build 650 had no 45s artificial deadline. Never reject an extraction
    // because the initial source PDF parse has not finished yet.
    const url=await prepareShiftPdfUrl(shift,text=>{
      if(!viewer.closed)viewer.document.body.textContent=text;
    });
    if(!url)throw new Error('Shift pages were not available');
    if(!viewer.closed)viewer.location.replace(url+'#page=1&zoom=page-width');
    setStatus('Opened '+pages.length+' original SPR page(s) for Shift '+shift+'.','success');
  }catch(error){
    console.warn('Shift '+shift+' original PDF extraction failed:',error);
    if(!viewer.closed){
      viewer.document.body.textContent='Could not extract Shift '+shift+': '+error.message;
      if(state.sourceUrl && !state.sourceUrl.startsWith('blob:')){
        const fallback=viewer.document.createElement('a');
        fallback.href=new URL(state.sourceUrl,document.baseURI).href+'#page='+pages[0];
        fallback.textContent='Open original SPR at Shift '+shift;
        viewer.document.body.append(viewer.document.createElement('p'),fallback);
      }
    }
    setStatus('Could not extract Shift '+shift+': '+error.message,'warning');
  }
}'''

def between(source,first,last,replacement,label):
    n=source.count(first)
    if n!=1:raise RuntimeError('Unexpected Build 683 '+label+' start ('+str(n)+')')
    a=source.index(first)
    b=source.find(last,a+len(first))
    if b<=a:raise RuntimeError('Unexpected Build 683 '+label+' end')
    return source[:a]+replacement.rstrip()+'\n'+source[b:]

def patch(source):
    if MARK in source:return source,False
    if '// SPR_BUILD683_RESTORED_650_FAST_SHIFT_CACHE' not in source:
        raise RuntimeError('Expected Build 683 frontend missing')
    # Explicitly preserve the index/search and the existing IndexedDB store.
    for key in ('SPR_MULTI_STORE',
                'function activateLoadedSprUi(', 'async function loadOnlinePdf(){',
                'function scheduleActivePdfPrefetch(){'):
        if key not in source:raise RuntimeError('Expected frontend state hook missing '+key)
    source=between(source,'let shiftSourceWarmEpoch=-1;','async function loadOnlinePdf(){',WARM,'PDF parse readiness')
    source=between(source,'async function prepareShiftPdfUrl(shift,onProgress=()=>{}){',
        '// Build 633:',PREPARE,'page extraction')
    source=between(source,'async function handleShiftSprClick(event){',
        'function collapseOtherTargetModules(',CLICK,'shift-click behaviour')

    # Crucial regression: the IndexedDB restore path reports "ready"
    # without starting source PDF parsing. Fix both restored and selected SPRs
    # at the common successful UI activation point.
    start=source.find('function activateLoadedSprUi(')
    end=source.find('async function restoreRetainedSpr(){',start)
    if start<0 or end<start:raise RuntimeError('Cannot find shared SPR UI activation')
    fragment=source[start:end]
    needle="  ui.showSprPanel.classList.remove('hidden');"
    if fragment.count(needle)!=1:raise RuntimeError('Shared UI shift-ready anchor ambiguous')
    fragment=fragment.replace(needle,needle+'''
  // The same path must initialise original-PDF Shift extraction after
  // manual Load AND after "Restored ... from this device".
  if(state.pdfBytes){
    scheduleShiftPdfWarmParse();
  }else{
    scheduleActivePdfPrefetch();
  }''',1)
    source=source[:start]+fragment+source[end:]

    # Remove stale "ready" label until the PDF parser has actually completed.
    early='    showShiftPdfReady();\n    scheduleShiftPdfWarmParse();'
    if source.count(early)!=1:raise RuntimeError('Expected existing early PDF-ready state not found')
    source=source.replace(early,'    scheduleShiftPdfWarmParse();',1)

    region=source[source.index('async function prepareShiftPdfUrl(shift,onProgress'):source.index('// Build 633:')]
    if 'extracted.copyPages(source,pages.map(p=>p-1))' not in region or any(x in region for x in ('getPreparedShiftPdf','canvas.toBlob','Rendering page')):
        raise RuntimeError('Page copying is not original selectable-PDF extraction')
    if 'Shift extraction exceeded 45 seconds' in source[source.index('async function handleShiftSprClick(event){'):source.index('function collapseOtherTargetModules(')]:
        raise RuntimeError('The early shift timeout was not removed')
    return MARK+'\n'+source,True

def hashbytes(data):return hashlib.sha256(data).hexdigest()
def read(sftp,path):
    with sftp.open(path,'rb') as f:return f.read()
def replace_checked(sftp,path,old,new):
    if hashbytes(read(sftp,path))!=hashbytes(old):
        raise RuntimeError('Concurrent website change: '+posixpath.basename(path))
    temp=path+'.build684-pending'
    try:
        with sftp.open(temp,'wb') as file:file.write(new)
        if hashbytes(read(sftp,temp))!=hashbytes(new):
            raise RuntimeError('SFTP staged SHA-256 mismatch')
        sftp.posix_rename(temp,path)
        if hashbytes(read(sftp,path))!=hashbytes(new):
            raise RuntimeError('SFTP final SHA-256 mismatch')
    finally:
        try:sftp.remove(temp)
        except Exception:pass

def main():
    e=os.environ
    for k in ('SFTP_HOST','SFTP_USERNAME','SFTP_PRIVATE_KEY_B64','SFTP_ROOT'):
        if not e.get(k):raise RuntimeError('Missing existing Bodgybros primary SFTP config '+k)
    root=posixpath.normpath(e['SFTP_ROOT'].replace('\\','/').strip())
    if root.endswith('/sps/spr/d') or root.endswith('/sps/spr/g'):
        root=posixpath.dirname(posixpath.dirname(posixpath.dirname(root)))
    elif root.endswith('/sps/spr'):root=posixpath.dirname(root)
    elif root.endswith('/public_html'):root=posixpath.join(root,'sps')
    if not root.endswith('/sps'):raise RuntimeError('Unsupported Bodgybros /sps path')
    text=base64.b64decode(e['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(text));break
        except Exception:pass
    if key is None:raise RuntimeError('Bodgybros private key format unsupported')
    ssh=paramiko.SSHClient()
    known='/data/credentials/spr-sftp-known_hosts'
    if not Path(known).exists():raise RuntimeError('Bodgybros SFTP known-host key missing')
    ssh.load_host_keys(known)
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=e['SFTP_HOST'],port=int(e.get('SFTP_PORT') or 22),
            username=e['SFTP_USERNAME'],pkey=key,timeout=12,
            auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
        with ssh.open_sftp() as sftp:
            path=posixpath.join(root,'script.js')
            original=read(sftp,path)
            amended,changed=patch(original.decode('utf-8'))
            if not changed:
                print('[684 ALREADY INSTALLED] Restored and loaded PDF shift readiness fixed',flush=True)
                return
            fd,tmp=tempfile.mkstemp(suffix='.js')
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as out:out.write(amended)
                check=subprocess.run(['node','--check',tmp],
                    capture_output=True,text=True,timeout=25)
                if check.returncode:raise RuntimeError('JavaScript syntax check failed: '+check.stderr[:500])
            finally:
                try:os.unlink(tmp)
                except OSError:pass
            files=[(path,original,amended.encode('utf-8'))]
            for name in ('index.php','index.html'):
                htmlpath=posixpath.join(root,name)
                old=read(sftp,htmlpath)
                html=old.decode('utf-8')
                if html.count('./script.js?v=683')!=1:
                    raise RuntimeError('Expected Build 683 HTML not active in '+name)
                html=html.replace('./script.js?v=683','./script.js?v=684',1)
                html=re.sub(r'(class=["\']build-number["\']>Build )683\b',r'\g<1>684',html,count=1)
                files.append((htmlpath,old,html.encode('utf-8')))
            backups=Path('/data/website-build684-backups')
            backups.mkdir(parents=True,exist_ok=True)
            for item,data,_ in files:(backups/posixpath.basename(item)).write_bytes(data)
            for item,before,after in files:
                replace_checked(sftp,item,before,after)
                print('[684 VERIFIED] '+posixpath.basename(item)+' SHA-256 '+hashbytes(after)[:14],flush=True)
            print('[684 READY] Build 650 retained PDF warmup, original page copying and automatic stale-buffer retry',flush=True)
    finally:ssh.close()
if __name__=='__main__':main()
