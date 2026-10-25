#!/usr/bin/env python3
"""Build 679: restore REAL, SELECTABLE, original SPR shift PDF pages on Bodgybros.

The actual pre-677 shift viewer code is restored by function boundaries, not
brittle comment matching. Supports only existing live Build 677. Does not
change indexed search, SPR parsing, rosters, authentication, source PDFs, or
prepared indexes. Applies atomically per-file after verifying remote SHA-256.
"""
import os,io,base64,posixpath,hashlib,re,subprocess,tempfile
from pathlib import Path
import paramiko

MARKER='// SPR_BODGYBROS_SHIFT_PDF_COPY_PAGES_679'

PREFETCH=r'''function scheduleActivePdfPrefetch(){
  // Once indexed results are available, download the original PDF in the
  // background; shift clicks use the same bytes, never page-to-image rendering.
  if(window.__SPR_PREINDEX_MODE||!state.pages.length||state.pdfBytes||!state.sourceUrl||
     state._pdfFetchPending||state._pdfPrefetchTimer)return;
  const epoch=activePdfSelectionEpoch;
  state._pdfPrefetchTimer=setTimeout(()=>{
    state._pdfPrefetchTimer=null;
    if(epoch!==activePdfSelectionEpoch||!state.pages.length||state.pdfBytes)return;
    ensureActivePdfBytes({background:true}).catch(error=>{
      if(error?.name!=='AbortError')console.debug('SPR PDF background prefetch unavailable; click can retry',error);
    });
  },80);
}
'''
ENSURE_BYTES=r'''async function ensureActivePdfBytes({background=false}={}){
  if(state.pdfBytes)return state.pdfBytes;
  if(!state.sourceUrl)throw new Error('Original SPR PDF URL not available');
  if(!background)setStatus('Preparing original '+state.fileName+' for shift pages…','info');
  if(state._pdfFetchPending)return await state._pdfFetchPending;
  const epoch=activePdfSelectionEpoch;
  const url=state.sourceUrl,controller=new AbortController();
  state._pdfFetchAbortController=controller;
  const promise=(async()=>{
    const buffer=await fetchArrayBufferResilient(url,{signal:controller.signal,background});
    if(controller.signal.aborted||epoch!==activePdfSelectionEpoch||state.sourceUrl!==url)
      throw new DOMException('SPR selection changed','AbortError');
    state.pdfBytes=buffer;
    schedulePersistLoadedSpr();
    // Preextract the first visible shift after loading, before its next click.
    scheduleVisibleShiftPdfPrewarm();
    return buffer;
  })();
  state._pdfFetchPending=promise;
  try{return await promise}
  finally{
    if(state._pdfFetchPending===promise)state._pdfFetchPending=null;
    if(state._pdfFetchAbortController===controller)state._pdfFetchAbortController=null;
  }
}
'''
EXTRACT=r'''async function prepareShiftPdfUrl(shift,onProgress=()=>{}){
  const value=normaliseRun(shift||'');
  if(!value||(!state.pages.length&&!state.pdfBytes))return '';
  const cached=state.shiftPdfUrls.get(value);
  if(cached)return cached;
  const pending=state.shiftPdfPromises.get(value);
  if(pending)return pending;
  const pages=[...new Set(state.shiftPages.get(value)||[])].sort((a,b)=>a-b);
  if(!pages.length)return '';
  const epoch=activePdfSelectionEpoch;
  const shiftUrlCache=state.shiftPdfUrls,shiftPromiseCache=state.shiftPdfPromises;
  const assertSameSpr=()=>{
    if(epoch!==activePdfSelectionEpoch)throw new DOMException('SPR selection changed','AbortError');
  };
  const promise=(async()=>{
    // Exact pages from the indexed ORIGINAL PDF, not rendered snapshots.
    await ensureActivePdfBytes();
    assertSameSpr();
    await ensurePdfLibraries();
    assertSameSpr();
    if(!state.pdfLibPromise)state.pdfLibPromise=PDFDocument.load(state.pdfBytes,{updateMetadata:false});
    const source=await state.pdfLibPromise;
    assertSameSpr();
    const extracted=await PDFDocument.create();
    const copied=await extracted.copyPages(source,pages.map(page=>page-1));
    assertSameSpr();
    copied.forEach(page=>extracted.addPage(page));
    const bytes=await extracted.save({useObjectStreams:false,addDefaultPage:false});
    assertSameSpr();
    const url=URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));
    if(epoch!==activePdfSelectionEpoch){URL.revokeObjectURL(url);assertSameSpr()}
    shiftUrlCache.set(value,url);
    return url;
  })();
  shiftPromiseCache.set(value,promise);
  try{return await promise}finally{
    if(shiftPromiseCache.get(value)===promise)shiftPromiseCache.delete(value);
  }
}
'''
PREWARM=r'''function scheduleVisibleShiftPdfPrewarm(){
  // Cache one visible shift during idle time. No eight-shift burst.
  if(shiftPrewarmHandle||!state.pdfBytes)return;
  const run=async()=>{
    shiftPrewarmHandle=0;
    const shifts=[...new Set([...ui.results.querySelectorAll('.shift-spr-link')]
      .map(a=>normaliseRun(a.dataset.shift||'')).filter(Boolean))].slice(0,1);
    for(const shift of shifts){
      if(state.shiftPdfUrls.has(shift))continue;
      try{await prepareShiftPdfUrl(shift)}
      catch(error){console.debug('SPR shift prewarm skipped',shift,error)}
    }
  };
  if('requestIdleCallback' in window)shiftPrewarmHandle=requestIdleCallback(run,{timeout:700});
  else shiftPrewarmHandle=setTimeout(run,120);
}
'''

def replace_between(code,start,end,new,label):
    left=code.find(start)
    if left<0 or code.find(start,left+len(start))>=0:
        raise RuntimeError('Shift viewer '+label+' entrypoint unavailable or ambiguous')
    right=code.find(end,left+len(start))
    if right<=left:raise RuntimeError('Shift viewer '+label+' end anchor absent')
    return code[:left]+new.rstrip()+'\n'+code[right:]

def patch(js):
    if MARKER in js:return js,False
    if '// SPR_BODGYBROS_INDEXED_SHIFT_677' not in js:
        raise RuntimeError('Live Bodgybros is not Build 677; refusing unrelated version')
    js=replace_between(js,'function scheduleActivePdfPrefetch(){',
        'async function ensureActivePdfBytes(',PREFETCH,'background prefetch')
    js=replace_between(js,'async function ensureActivePdfBytes({background=false}={}){',
        'async function loadOnlinePdf(){',ENSURE_BYTES,'download and prewarm')
    js=replace_between(js,'async function prepareShiftPdfUrl(shift,onProgress=()=>{}){',
        '// Build 633:',EXTRACT,'original PDF page extraction')
    js=replace_between(js,'function scheduleVisibleShiftPdfPrewarm(){',
        'new MutationObserver(',PREWARM,'idle shift PDF cache')
    js=MARKER+'\n'+js
    if js.count('async function prepareShiftPdfUrl(shift,onProgress=()=>{}){')!=1:
        raise RuntimeError('Shift extractor is not unique')
    shift=js.split('async function prepareShiftPdfUrl(shift,onProgress=()=>{}){',1)[1].split('// Build 633:',1)[0]
    if 'extracted.copyPages(source,pages.map(page=>page-1))' not in shift:
        raise RuntimeError('Text-preserving original PDF copyPages is missing')
    if any(x in shift for x in ('prepareKustomFastShiftPdf','canvas.toDataURL','canvas.toBlob','Rendering page')):
        raise RuntimeError('Shift viewer still renders page images; refusing install')
    if 'scheduleActivePdfPrefetch();' not in js or 'scheduleVisibleShiftPdfPrewarm();' not in js:
        raise RuntimeError('Background SPR PDF prefetch/prewarm not connected')
    if 'Shift page extraction exceeded 45 seconds' not in js:
        raise RuntimeError('Shift viewer timeout safety lost')
    return js,True

def sha(data):return hashlib.sha256(data).hexdigest()
def read(sftp,path):
    with sftp.open(path,'rb') as f:return f.read()
def root_path(raw):
    root=posixpath.normpath(raw.strip().replace('\\','/'))
    if root.endswith('/sps'):return root
    if root.endswith('/sps/spr'):return posixpath.dirname(root)
    if root.endswith('/sps/spr/d') or root.endswith('/sps/spr/g'):
        return posixpath.dirname(posixpath.dirname(posixpath.dirname(root)))
    if root.endswith('/public_html'):return posixpath.join(root,'sps')
    raise RuntimeError('Unexpected Bodgybros SFTP_ROOT')

def write(sftp,path,before,after):
    if sha(read(sftp,path))!=sha(before):
        raise RuntimeError('Website file changed concurrently: '+posixpath.basename(path))
    temp=path+'.build679-temp'
    try:
        with sftp.open(temp,'wb') as f:f.write(after)
        if sha(read(sftp,temp))!=sha(after):
            raise RuntimeError('Temporary SFTP SHA-256 mismatch')
        sftp.posix_rename(temp,path)
        if sha(read(sftp,path))!=sha(after):
            raise RuntimeError('Final SFTP SHA-256 mismatch')
    finally:
        try:sftp.remove(temp)
        except Exception:pass

def main():
    for name in ('SFTP_HOST','SFTP_USERNAME','SFTP_PRIVATE_KEY_B64','SFTP_ROOT'):
        if not os.environ.get(name):
            raise RuntimeError('Missing existing Bodgybros SFTP configuration: '+name)
    keys=Path('/data/credentials/spr-sftp-known_hosts')
    if not keys.exists():raise RuntimeError('Expected known Bodgybros SFTP host key is missing')
    key_text=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=typ.from_private_key(io.StringIO(key_text));break
        except Exception:pass
    if key is None:raise RuntimeError('Existing SFTP key format unsupported')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(keys))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=os.environ['SFTP_HOST'],
            port=int(os.environ.get('SFTP_PORT') or 22),
            username=os.environ['SFTP_USERNAME'],pkey=key,timeout=10,
            auth_timeout=12,banner_timeout=12,
            allow_agent=False,look_for_keys=False)
        with ssh.open_sftp() as sftp:
            base=root_path(os.environ['SFTP_ROOT'])
            js_path=posixpath.join(base,'script.js')
            original=read(sftp,js_path)
            updated,changed=patch(original.decode('utf-8'))
            if not changed:
                print('[BUILD 679] Original shift PDF extraction already installed',flush=True)
                return
            files=[(js_path,original,updated.encode('utf-8'))]
            for name in ('index.php','index.html'):
                path=posixpath.join(base,name)
                old=read(sftp,path)
                html=old.decode('utf-8')
                if html.count('./script.js?v=677')!=1:
                    raise RuntimeError(name+' expected build 677 script version absent')
                html=html.replace('./script.js?v=677','./script.js?v=679',1)
                html=re.sub(r'(class=["\']build-number["\']>Build )677\b',r'\g<1>679',html,count=1)
                files.append((path,old,html.encode('utf-8')))
            backups=Path('/data/website-build679-backups')
            backups.mkdir(parents=True,exist_ok=True)
            for path,old,_ in files:
                (backups/posixpath.basename(path)).write_bytes(old)
            for path,old,new in files:
                write(sftp,path,old,new)
                print('[BUILD 679 ORIGINAL PDF PAGES] '+posixpath.basename(path)+' '+sha(new)[:14],flush=True)
    finally:ssh.close()

if __name__=='__main__':main()
