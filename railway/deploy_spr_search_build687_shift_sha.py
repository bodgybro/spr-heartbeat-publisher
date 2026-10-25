#!/usr/bin/env python3
"""Build 687 live patch: verify original PDF SHA before opening linked shift pages.

SFTP-only targeted update of script.js and Build labels; preserves SPR files,
rosters, auth, and all existing frontend parsing and shift extraction behaviour.
Idempotent on restart and refuses unrecognised source shapes.
"""
import os,io,base64,posixpath,hashlib,re
from pathlib import Path
import paramiko

def digest(b):return hashlib.sha256(b).hexdigest()
def one(source,old,new,label):
    n=source.count(old)
    if n!=1:raise RuntimeError('Build 687 expected '+label+' exactly once, found '+str(n))
    return source.replace(old,new,1)

HELPER=r"""// Build 687: shift page extraction must use the same source PDF as the
// indexed shift. A device may still have the pre-repair 26 Oct Guards PDF
// (which contained Drivers pages) in its HTTP or IndexedDB cache.
const sprVerifiedOriginalBuffers=new WeakSet();
async function sprOriginalPdfMatchesIndex(buffer){
  if(!buffer)return false;
  if(!/^[a-f0-9]{64}$/i.test(state.sourceSha||''))return true;
  if(sprVerifiedOriginalBuffers.has(buffer))return true;
  const hash=new Uint8Array(await crypto.subtle.digest('SHA-256',buffer));
  const actual=Array.from(hash,b=>b.toString(16).padStart(2,'0')).join('');
  if(actual.toLowerCase()!==state.sourceSha.toLowerCase())return false;
  sprVerifiedOriginalBuffers.add(buffer);
  return true;
}
function sprDiscardWrongOriginalPdf(){
  state.pdfBytes=null;
  state.pdfLibPromise=null;
  state.pdfDoc=null;
  shiftSourceWarmEpoch=-1;
  shiftSourceWarmPromise=null;
  for(const url of state.shiftPdfUrls.values())try{URL.revokeObjectURL(url)}catch(_){}
  state.shiftPdfUrls.clear();
  if(ui.summary.textContent.includes('Original Shift PDFs ready'))
    ui.summary.textContent=ui.summary.textContent.replace(' · Original Shift PDFs ready','');
}
"""

def patch_js(source):
    if 'const sprVerifiedOriginalBuffers=new WeakSet();' in source:
        print('  [BUILD 687 JS] Already installed; unchanged',flush=True)
        return source
    if 'function sprSelectionMatches(' not in source or 'async function prepareShiftPdfUrl(' not in source:
        raise RuntimeError('Unexpected live script.js: Build 686 selection guards are missing')
    source=one(source,
        "async function fetchArrayBufferResilient(relativeUrl,{signal=null,background=false}={}){",
        "async function fetchArrayBufferResilient(relativeUrl,{signal=null,background=false,fresh=false}={}){",
        'fresh fetch option')
    source=one(source,
        "const response=await fetch(absUrl,{credentials:'same-origin',cache:'default',",
        "const response=await fetch(absUrl,{credentials:'same-origin',cache:fresh?'no-store':'default',",
        'no-store fetch')
    source=one(source,"let activePdfSelectionEpoch=0;\n",
        "let activePdfSelectionEpoch=0;\n"+HELPER,'source identity helpers')
    source=one(source,
        """async function ensureActivePdfBytes({background=false}={}){
  if(state.pdfBytes)return state.pdfBytes;
  if(!state.sourceUrl)throw new Error('Original SPR PDF URL not available');
""",
        """async function ensureActivePdfBytes({background=false}={}){
  if(state.pdfBytes){
    if(await sprOriginalPdfMatchesIndex(state.pdfBytes))return state.pdfBytes;
    console.warn('Original SPR cache is for a different PDF; discarding stale pages before shift extraction');
    sprDiscardWrongOriginalPdf();
  }
  if(!state.sourceUrl)throw new Error('Original SPR PDF URL not available');
""",'cached bytes verification')
    source=one(source,
        """    const buffer=await fetchArrayBufferResilient(url,{signal:controller.signal,background});
    if(controller.signal.aborted||epoch!==activePdfSelectionEpoch||state.sourceUrl!==url)
      throw new DOMException('SPR selection changed','AbortError');
    if(!buffer||buffer.byteLength<1000)throw new Error('Original SPR PDF download is empty');
    state.pdfBytes=buffer;
""",
        """    let buffer=await fetchArrayBufferResilient(url,{signal:controller.signal,background});
    if(controller.signal.aborted||epoch!==activePdfSelectionEpoch||state.sourceUrl!==url)
      throw new DOMException('SPR selection changed','AbortError');
    if(!buffer||buffer.byteLength<1000)throw new Error('Original SPR PDF download is empty');
    if(!await sprOriginalPdfMatchesIndex(buffer)){
      console.warn('Cached original SPR does not match the published index SHA-256; fetching a fresh PDF');
      if(!background)setStatus('Refreshing the correct original SPR PDF for shift pages…','info');
      const freshUrl=new URL(url,document.baseURI);
      freshUrl.searchParams.set('spr_source',state.sourceSha.slice(0,16));
      freshUrl.searchParams.set('spr_reload',String(Date.now()));
      buffer=await fetchArrayBufferResilient(freshUrl.href,{signal:controller.signal,background,fresh:true});
      if(!await sprOriginalPdfMatchesIndex(buffer))
        throw new Error('Original SPR PDF differs from its search index. Shift pages were not opened.');
    }
    if(controller.signal.aborted||epoch!==activePdfSelectionEpoch||state.sourceUrl!==url)
      throw new DOMException('SPR selection changed','AbortError');
    state.pdfBytes=buffer;
""",'network PDF identity')
    source=one(source,
        """  if(state.pdfBytes){
    scheduleShiftPdfWarmParse();
  }else{
""",
        """  if(state.pdfBytes){
    if(state.sourceSha)ensureActivePdfBytes().then(()=>scheduleShiftPdfWarmParse())
      .catch(error=>console.warn('Retained shift-source verification failed',error));
    else scheduleShiftPdfWarmParse();
  }else{
""",'cache restore')
    source=one(source,
        """async function prepareShiftPdfUrl(shift,onProgress=()=>{}){
  const value=normaliseRun(shift||'');
  if(!value||!state.pages.length)return '';
  const ready=state.shiftPdfUrls.get(value);
""",
        """async function prepareShiftPdfUrl(shift,onProgress=()=>{}){
  const value=normaliseRun(shift||'');
  if(!value||!state.pages.length)return '';
  // A cached shift PDF may be trusted only after source SHA validation.
  if(state.sourceSha){
    onProgress('Checking original SPR PDF for Shift '+value+'…');
    await ensureActivePdfBytes();
  }
  const ready=state.shiftPdfUrls.get(value);
""",'prevent prewarmed PDF bypass')
    source=one(source,
        """    if(!state.pdfBytes){
      onProgress('Downloading original SPR once for Shift '+value+'…');
      await ensureActivePdfBytes();
    }
    sameSelection();
    await ensurePdfLibraries();
""",
        """    if(!state.pdfBytes){
      onProgress('Downloading original SPR once for Shift '+value+'…');
      await ensureActivePdfBytes();
    }
    if(state.sourceSha)await ensureActivePdfBytes();
    sameSelection();
    await ensurePdfLibraries();
""",'verify extraction source')
    source=one(source,
        """  const cached=state.shiftPdfUrls.get(shift);
  if(cached){
    viewer.location.replace(cached+'#page=1&zoom=page-width');
    return;
  }
""",
        """  // Never bypass prepareShiftPdfUrl's source validation for a
  // previously cached shift PDF.
""",'viewer cache bypass')
    return source

def patch_html(n,source):
    if 'Build 687' in source:
        print('  [BUILD 687 HTML] Already updated '+n,flush=True)
        return source
    if 'Build 686' not in source:raise RuntimeError('Unexpected '+n+' build label')
    # A PHP file may assemble script loading dynamically, so update only
    # explicit versioned script references if they exist.
    source=source.replace('script.js?v=686','script.js?v=687')
    source=one(source,'class="build-number">Build 686',
                      'class="build-number">Build 687',n+' label')
    return source

def remote_root():
    root=os.environ['SFTP_ROOT'].replace('\\','/').rstrip('/')
    if root.endswith('/sps/spr'):return root[:-4]
    if root.endswith('/sps'):return root
    if root.endswith('/public_html') or root=='public_html':return root+'/sps'
    raise RuntimeError('Unexpected SFTP root, refusing deployment')

def main():
    raw=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=typ.from_private_key(io.StringIO(raw));break
        except Exception:continue
    if key is None:raise RuntimeError('Invalid existing SFTP key')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ['SFTP_HOST'],username=os.environ['SFTP_USERNAME'],
                port=int(os.environ.get('SFTP_PORT') or 22),pkey=key,
                timeout=12,auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
    sftp=ssh.open_sftp()
    root=remote_root()
    try:
        original={};changed={}
        for n in ('script.js','index.php','index.html'):
            remote=posixpath.join(root,n)
            with sftp.open(remote,'rb') as f:old=f.read()
            text=old.decode('utf-8')
            fresh=(patch_js(text) if n=='script.js' else patch_html(n,text)).encode('utf-8')
            original[n]=old
            if fresh!=old:changed[n]=fresh
            print('  [BUILD 687 SOURCE] '+n+' '+digest(old)[:12]+' -> '+digest(fresh)[:12],flush=True)
        if not changed:
            print('  [BUILD 687 COMPLETE] Already deployed; no changes needed',flush=True)
            return
        stage=[]
        try:
            for n,data in changed.items():
                remote=posixpath.join(root,n)
                temp=remote+'.b687-stage-'+str(os.getpid())
                with sftp.open(temp,'wb') as f:f.write(data)
                with sftp.open(temp,'rb') as f:validated=f.read()
                if digest(validated)!=digest(data):raise RuntimeError('Staging checksum failure: '+n)
                stage.append((n,remote,temp))
            replaced=[]
            try:
                for n,remote,temp in stage:
                    sftp.posix_rename(temp,remote)
                    replaced.append(n)
                    with sftp.open(remote,'rb') as f:validated=f.read()
                    if digest(validated)!=digest(changed[n]):raise RuntimeError('Live checksum failure: '+n)
                    print('  [BUILD 687 LIVE VERIFIED] '+n+' '+digest(changed[n])[:12],flush=True)
            except Exception:
                for n in reversed(replaced):
                    remote=posixpath.join(root,n)
                    temp=remote+'.b687-rollback-'+str(os.getpid())
                    with sftp.open(temp,'wb') as f:f.write(original[n])
                    sftp.posix_rename(temp,remote)
                    print('  [BUILD 687 ROLLED BACK] '+n,flush=True)
                raise
            print('  [BUILD 687 COMPLETE] Shift source SHA validation deployed; source PDFs and rosters untouched',flush=True)
        finally:
            for n,remote,temp in stage:
                try:sftp.remove(temp)
                except Exception:pass
    finally:
        sftp.close();ssh.close()

if __name__=='__main__':main()
