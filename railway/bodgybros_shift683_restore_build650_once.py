#!/usr/bin/env python3
"""Build 683: restore the actual Build 650 original SPR page extraction.

Keep Build 679 prepared-index search and multi-day browser IndexedDB caching.
Remove the blocked Build 680-681 manifest/shift-file click path.
Never rasterise pages; copy from already-cached original PDF bytes.
No changes to search/roster/SPR parser/source PDFs; backed-up SHA-verified SFTP.
"""
import os,io,base64,posixpath,hashlib,re,subprocess,tempfile
from pathlib import Path
import paramiko

MARK='// SPR_BUILD683_RESTORED_650_FAST_SHIFT_CACHE'
EXTRACT=r'''async function prepareShiftPdfUrl(shift,onProgress=()=>{}){
  const value=normaliseRun(shift||'');
  if(!value||!state.pages.length)return '';
  const cached=state.shiftPdfUrls.get(value);
  if(cached)return cached;
  const existing=state.shiftPdfPromises.get(value);
  if(existing)return existing;
  const pages=[...new Set(state.shiftPages.get(value)||[])].sort((a,b)=>a-b);
  if(!pages.length)return '';
  const epoch=activePdfSelectionEpoch;
  const urlCache=state.shiftPdfUrls,pendingCache=state.shiftPdfPromises;
  const check=()=>{
    if(epoch!==activePdfSelectionEpoch)throw new DOMException('SPR selection changed','AbortError');
  };
  const task=(async()=>{
    // Build 650: keep the COMPLETE ORIGINAL PDF in memory and copy its
    // underlying PDF pages. No PDF.js canvas or image conversion.
    if(!state.pdfBytes){
      onProgress('Loading original SPR for Shift '+value+' (one download per unchanged SPR)…');
      await ensureActivePdfBytes();
    }
    check();
    await ensurePdfLibraries();
    check();
    if(!state.pdfLibPromise){
      const promise=PDFDocument.load(state.pdfBytes,{updateMetadata:false});
      state.pdfLibPromise=promise;
    }
    const source=await state.pdfLibPromise;
    check();
    const output=await PDFDocument.create();
    const originals=await output.copyPages(source,pages.map(n=>n-1));
    check();
    originals.forEach(page=>output.addPage(page));
    const bytes=await output.save({useObjectStreams:false,addDefaultPage:false});
    check();
    const url=URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));
    if(epoch!==activePdfSelectionEpoch){
      URL.revokeObjectURL(url);
      check();
    }
    urlCache.set(value,url);
    return url;
  })();
  pendingCache.set(value,task);
  try{return await task}
  finally{if(pendingCache.get(value)===task)pendingCache.delete(value)}
}'''

PREFETCH=r'''function scheduleActivePdfPrefetch(){
  if(window.__SPR_PREINDEX_MODE||!state.pages.length||state.pdfBytes||
     !state.sourceUrl||state._pdfFetchPending||state._pdfPrefetchTimer)return;
  const epoch=activePdfSelectionEpoch;
  state._pdfPrefetchTimer=setTimeout(()=>{
    state._pdfPrefetchTimer=null;
    if(epoch!==activePdfSelectionEpoch||!state.pages.length||state.pdfBytes)return;
    ensureActivePdfBytes({background:true}).catch(error=>{
      if(error?.name!=='AbortError')console.warn('Original SPR PDF prefetch failed; click can retry',error);
    });
  },50);
}
'''
ENSURE=r'''async function ensureActivePdfBytes({background=false}={}){
  if(state.pdfBytes)return state.pdfBytes;
  if(!state.sourceUrl)throw new Error('Original SPR PDF URL not available');
  if(state._pdfFetchPending)return await state._pdfFetchPending;
  if(!background)setStatus('Downloading original SPR PDF once for shift links…','info');
  const epoch=activePdfSelectionEpoch;
  const url=state.sourceUrl,controller=new AbortController();
  state._pdfFetchAbortController=controller;
  const promise=(async()=>{
    const buffer=await fetchArrayBufferResilient(url,{signal:controller.signal,background});
    if(controller.signal.aborted||epoch!==activePdfSelectionEpoch||state.sourceUrl!==url)
      throw new DOMException('SPR selection changed','AbortError');
    if(!buffer||buffer.byteLength<1000)throw new Error('Original SPR PDF download is empty');
    state.pdfBytes=buffer;
    // The existing IndexedDB store retains full PDF bytes by selected
    // date/role; no redownload on subsequent selection if still cached.
    schedulePersistLoadedSpr();
    showShiftPdfReady();
    scheduleShiftPdfWarmParse();
    scheduleVisibleShiftPdfPrewarm();
    return state.pdfBytes;
  })();
  state._pdfFetchPending=promise;
  try{return await promise}
  finally{
    if(state._pdfFetchPending===promise)state._pdfFetchPending=null;
    if(state._pdfFetchAbortController===controller)state._pdfFetchAbortController=null;
  }
}
let shiftSourceWarmEpoch=-1;
function showShiftPdfReady(){
  if(!state.pdfBytes||!state.pages.length)return;
  const suffix=' · Original Shift PDFs ready';
  if(!ui.summary.textContent.includes(suffix))ui.summary.textContent+=suffix;
}
function scheduleShiftPdfWarmParse(){
  if(!state.pdfBytes||!state.pages.length)return;
  const epoch=activePdfSelectionEpoch;
  if(shiftSourceWarmEpoch===epoch)return;
  shiftSourceWarmEpoch=epoch;
  const work=async()=>{
    if(epoch!==activePdfSelectionEpoch||!state.pdfBytes)return;
    try{
      await ensurePdfLibraries();
      if(epoch!==activePdfSelectionEpoch)return;
      if(!state.pdfLibPromise)state.pdfLibPromise=PDFDocument.load(state.pdfBytes,{updateMetadata:false});
      await state.pdfLibPromise;
      if(epoch===activePdfSelectionEpoch)scheduleVisibleShiftPdfPrewarm();
    }catch(error){
      if(epoch===activePdfSelectionEpoch){
        state.pdfLibPromise=null;
        console.warn('Shift PDF background preparation failed; click can retry',error);
      }
    }
  };
  if('requestIdleCallback' in window)requestIdleCallback(work,{timeout:1200});
  else setTimeout(work,150);
}
'''

PREWARM=r'''function scheduleVisibleShiftPdfPrewarm(){
  if(shiftPrewarmHandle||!state.pdfBytes||window.__SPR_PREINDEX_MODE)return;
  const epoch=activePdfSelectionEpoch;
  const run=async()=>{
    shiftPrewarmHandle=0;
    if(epoch!==activePdfSelectionEpoch||!state.pdfBytes)return;
    // Build 650 cached result-link shift PDFs before clicks. Keep one
    // background extraction at a time to avoid the Build 663 slowdown.
    const shifts=[...new Set([...ui.results.querySelectorAll('.shift-spr-link')]
       .map(a=>normaliseRun(a.dataset.shift||'')).filter(Boolean))].slice(0,4);
    for(const shift of shifts){
      if(epoch!==activePdfSelectionEpoch)return;
      if(state.shiftPdfUrls.has(shift)||state.shiftPdfPromises.has(shift))continue;
      try{await prepareShiftPdfUrl(shift)}
      catch(error){console.debug('Original shift PDF prewarm skipped',shift,error)}
      // Yield to an actual click instead of monopolising the UI.
      await new Promise(resolve=>setTimeout(resolve,0));
    }
  };
  if('requestIdleCallback' in window)shiftPrewarmHandle=requestIdleCallback(run,{timeout:750});
  else shiftPrewarmHandle=setTimeout(run,100);
}
'''

CLICK=r'''async function handleShiftSprClick(event){
  const link=event.target.closest('.shift-spr-link');
  if(!link)return;
  event.preventDefault();
  const shift=normaliseRun(link.dataset.shift||'');
  const pages=[...new Set(state.shiftPages.get(shift)||[])].sort((a,b)=>a-b);
  if(!pages.length||(!state.pdfBytes&&!state.sourceUrl)){
    setStatus('Original SPR pages for Shift '+shift+' were not identified.','warning');return;
  }
  const viewer=window.open('about:blank','_blank');
  if(!viewer){setStatus('Allow pop-ups to open shift SPR pages.','warning');return}
  viewer.document.title='Shift '+shift;
  // Open cached original pages immediately, just as in Build 650.
  const ready=state.shiftPdfUrls.get(shift);
  if(ready){
    viewer.location.replace(ready+'#page=1&zoom=page-width');
    return;
  }
  viewer.document.body.textContent=state.pdfBytes
    ?'Extracting '+pages.length+' original PDF page(s) for Shift '+shift+'…'
    :'Loading the original SPR PDF for Shift '+shift+'…';
  try{
    let timer;
    const url=await Promise.race([
      prepareShiftPdfUrl(shift,text=>{
        if(!viewer.closed)viewer.document.body.textContent=text;
      }),
      new Promise((_,reject)=>{timer=setTimeout(
        ()=>reject(new Error('Shift extraction exceeded 45 seconds')),45000)})
    ]).finally(()=>clearTimeout(timer));
    if(!url)throw new Error('Original shift pages were unavailable');
    if(!viewer.closed)viewer.location.replace(url+'#page=1&zoom=page-width');
    setStatus('Opened '+pages.length+' original SPR page(s) for Shift '+shift+'.','success');
  }catch(error){
    console.error('Shift '+shift+' extraction failed:',error);
    if(!viewer.closed){
      viewer.document.body.textContent='Could not open Shift '+shift+': '+error.message;
      if(state.sourceUrl){
        const fallback=viewer.document.createElement('a');
        fallback.href=new URL(state.sourceUrl,document.baseURI).href+'#page='+pages[0];
        fallback.textContent='Open original SPR at Shift '+shift;
        fallback.target='_self';
        viewer.document.body.append(viewer.document.createElement('p'),fallback);
      }
    }
    setStatus('Could not open Shift '+shift+': '+error.message,'warning');
  }
}'''

def block(source,start,end,replacement,label):
    start_at=source.find(start)
    next_at=source.find(start,start_at+len(start)) if start_at>=0 else -1
    end_at=source.find(end,start_at+len(start)) if start_at>=0 else -1
    if start_at<0 or next_at>=0 or end_at<start_at:
        raise RuntimeError('Expected exact '+label+' block not found uniquely')
    return source[:start_at]+replacement.rstrip()+'\n'+source[end_at:]

def patch(source):
    if MARK in source:return source,False
    required=(
        'function scheduleActivePdfPrefetch(){',
        'async function ensureActivePdfBytes({background=false}={}){',
        'async function prepareShiftPdfUrl(shift,onProgress=()=>{}){',
        'function scheduleVisibleShiftPdfPrewarm(){',
        'async function handleShiftSprClick(event){',
        'SPR_PREEXTRACTED_ORIGINAL_SHIFT_PDF_680',
        'SPR_SHIFT_CACHE_PHP_681',
        'const SPR_MULTI_STORE')
    for anchor in required:
        if anchor not in source:raise RuntimeError('Live website not the expected Build 681: '+anchor)
    # Remove Build 680-681 manifest and PHP client code completely.
    head='// Railway has already copied the indexed ORIGINAL pages into separate PDFs.'
    source=block(source,head,'async function handleShiftSprClick(event){','',
                 'obsolete prepared-PDF HTTP client')
    source=block(source,'async function handleShiftSprClick(event){',
       'function collapseOtherTargetModules(',CLICK,'shift click')
    source=block(source,'async function prepareShiftPdfUrl(shift,onProgress=()=>{}){',
       '// Build 633:',EXTRACT,'real original PDF extraction')
    source=block(source,'function scheduleVisibleShiftPdfPrewarm(){',
       'new MutationObserver(',PREWARM,'idle shift PDF cache')
    source=block(source,'function scheduleActivePdfPrefetch(){',
       'async function ensureActivePdfBytes(',PREFETCH,'background source PDF prefetch')
    source=block(source,'async function ensureActivePdfBytes({background=false}={}){',
       'async function loadOnlinePdf(){',ENSURE,'original PDF byte cache')
    needle='    scheduleActivePdfPrefetch();\n    warmSecondaryShiftSource();'
    if source.count(needle)!=1:
        raise RuntimeError('Retained index restore and original PDF prewarm call differ')
    source=source.replace(needle,
        '    scheduleActivePdfPrefetch();\n    if(state.pdfBytes){showShiftPdfReady();scheduleShiftPdfWarmParse();}\n    warmSecondaryShiftSource();',1)
    if any(token in source[source.find('async function prepareShiftPdfUrl(shift,onProgress'):source.find('// Build 633:')] for token in
           ('prepareKustomFastShiftPdf','canvas.toBlob','getPreparedShiftPdf','Rendering page')):
        raise RuntimeError('A rasterising or manifest path survived the actual shift extractor')
    if 'extracted.copyPages' in source and 'output.copyPages(source,pages.map(n=>n-1))' not in source:
        raise RuntimeError('Expected original PDF copyPages not installed')
    if source.count('async function prepareShiftPdfUrl(shift,onProgress=()=>{}){')!=1:
        raise RuntimeError('Shift extractor duplicate after edit')
    return MARK+'\n'+source,True

def digest(data):return hashlib.sha256(data).hexdigest()
def get(sftp,path):
    with sftp.open(path,'rb') as file:return file.read()
def atomic(sftp,path,old,new):
    if digest(get(sftp,path))!=digest(old):
        raise RuntimeError('Concurrent website edit: '+posixpath.basename(path))
    tmp=path+'.fastshift683-new'
    try:
        with sftp.open(tmp,'wb') as f:f.write(new)
        if digest(get(sftp,tmp))!=digest(new):
            raise RuntimeError('Temporary SFTP checksum verification failed')
        sftp.posix_rename(tmp,path)
        if digest(get(sftp,path))!=digest(new):
            raise RuntimeError('Final SFTP checksum verification failed')
    finally:
        try:sftp.remove(tmp)
        except Exception:pass

def main():
    env=os.environ
    for name in ('SFTP_HOST','SFTP_USERNAME','SFTP_PRIVATE_KEY_B64','SFTP_ROOT'):
        if not env.get(name):raise RuntimeError('Existing Bodgybros SFTP setting missing: '+name)
    root=posixpath.normpath(env['SFTP_ROOT'].strip().replace('\\','/'))
    if root.endswith('/sps/spr/d') or root.endswith('/sps/spr/g'):
        root=posixpath.dirname(posixpath.dirname(posixpath.dirname(root)))
    elif root.endswith('/sps/spr'):root=posixpath.dirname(root)
    elif root.endswith('/public_html'):root=posixpath.join(root,'sps')
    if not root.endswith('/sps'):raise RuntimeError('Unrecognised Bodgybros website SFTP root')
    pem=base64.b64decode(env['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=typ.from_private_key(io.StringIO(pem));break
        except Exception:pass
    if key is None:raise RuntimeError('Existing Bodgybros SFTP private key not usable')
    ssh=paramiko.SSHClient()
    kh='/data/credentials/spr-sftp-known_hosts'
    if not Path(kh).exists():raise RuntimeError('Previously verified primary SFTP host key missing')
    ssh.load_host_keys(kh)
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=env['SFTP_HOST'],port=int(env.get('SFTP_PORT') or 22),
          username=env['SFTP_USERNAME'],pkey=key,timeout=12,
          auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
        with ssh.open_sftp() as sftp:
            path=posixpath.join(root,'script.js')
            original=get(sftp,path)
            output,changed=patch(original.decode('utf-8'))
            if not changed:
                print('[683 ALREADY INSTALLED] Build 650 original shift PDF caching restored',flush=True)
                return
            fd,tmp=tempfile.mkstemp(suffix='.js')
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as fh:fh.write(output)
                result=subprocess.run(['node','--check',tmp],capture_output=True,text=True,timeout=20)
                if result.returncode:
                    raise RuntimeError('Patched shift JavaScript syntax check failed: '+result.stderr[:400])
            finally:
                try:os.unlink(tmp)
                except OSError:pass
            files=[(path,original,output.encode('utf-8'))]
            for name in ('index.php','index.html'):
                docpath=posixpath.join(root,name)
                before=get(sftp,docpath)
                html=before.decode('utf-8')
                if html.count('./script.js?v=681')!=1:
                    raise RuntimeError(name+' Build 681 JS version key missing; website not modified')
                html=html.replace('./script.js?v=681','./script.js?v=683',1)
                html=re.sub(r'(class=["\']build-number["\']>Build )681\b',r'\g<1>683',html,count=1)
                files.append((docpath,before,html.encode('utf-8')))
            backup=Path('/data/website-build683-backups')
            backup.mkdir(parents=True,exist_ok=True)
            for p,old,_ in files:
                (backup/posixpath.basename(p)).write_bytes(old)
            for p,old,new in files:
                atomic(sftp,p,old,new)
                print('[683 VERIFIED] '+posixpath.basename(p)+' SHA-256 '+digest(new)[:14],flush=True)
            # The old PHP endpoint is no longer used; retain the read-only
            # file for a rollback instead of deleting anything unexpectedly.
            print('[683 RESTORED] Build 650 original page copying, byte caching, background prefetch; no metadata HTTP dependency',flush=True)
    finally:ssh.close()
if __name__=='__main__':main()
