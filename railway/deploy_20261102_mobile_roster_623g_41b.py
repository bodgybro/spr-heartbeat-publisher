#!/usr/bin/env python3
"""Guarded Build 700 release: iOS roster Shift 224 memory; 3 Nov run origins.

One-at-a-time Daily roster parsing on iOS; preserve all-depot active/FDW logic,
saved indexes, and fast desktop behavior. Correct only the reported Drivers
3 Nov 623G missing origin and Fuller's Relieve 41-B handover station.
Create a NEW JS filename to bypass previously stale mobile caches. Verify
staged and final SHA-256 for each SFTP file; rollback on any failure.
"""
import os,io,base64,posixpath,re,hashlib
import paramiko

EXPECTED_JS="6b11ee68197215aeb64d917ad610fec3"
OLD_JS="script-700-578b-location-v3.js"
NEW_JS="script-700-mobile-224-3nov-v1.js"
MARKER="SPR_MOBILE_224_NOV3_FIX_20261102"

def exact(s,old,new,label):
    if s.count(old)!=1:raise RuntimeError("Source differs in "+label+"; no live changes")
    return s.replace(old,new,1)
def one_regex(s,pattern,replacement,label):
    p=re.compile(pattern,re.S)
    matches=list(p.finditer(s))
    if len(matches)!=1:raise RuntimeError("Source differs in "+label+"; "+str(len(matches))+" matches")
    m=matches[0]
    return s[:m.start()]+replacement+s[m.end():]

def patch(js):
    if MARKER in js:raise RuntimeError("Already patched")
    for token in ("function renderCard(r){","function renderShiftCard(shift){",
                  "function sprOriginalPdfMatchesIndex(",
                  "SPR_578B_LOCATION_DISPLAY_V3_20261101",
                  "SPR_568B_578B_ORIGIN_CONDITION_V2",
                  "// SPR_SORT_RUN_START_20261101"):
        if token not in js:raise RuntimeError("Required working marker missing "+token)
    helpers=r'''
// SPR_MOBILE_224_NOV3_FIX_20261102
function rosterShiftLowMemoryDevice(){
  return /iP(?:hone|ad|od)/i.test(navigator.userAgent||'');
}
async function* rosterDailySourcesLowMemory(date,role,allDaily,{announce=false}={}){
  const depots=await rosterGetAllDepots();
  if(!depots.length)throw new Error('No depot rosters are available.');
  allDaily.total=depots.length;
  let checked=0;
  for(const depot of depots){
    const depotName=rosterDisplayName(depot.name||'Depot');
    const periodUrl=rosterVirtualUrl(depot.url,role,'Daily Roster');
    try{
      const j=await rosterList(periodUrl),pdfs=rosterPdfs(j.items);
      const chosen=rosterChoosePdf(pdfs,role,'Daily Roster');
      if(!chosen)throw new Error('No Daily roster PDF');
      const name=chosen.name||(depotName+' '+role+' Daily.pdf');
      const snapshot=await rosterLoadPdfSnapshot(chosen.url,name);
      if(!snapshot.pages.some(page=>!!rosterSelectedDateColumn(page,date))){
        allDaily.missingDate.push({depot:depotName});
        await rosterReleaseDailySource({pdfUrl:chosen.url,snapshot});
      }else{
        allDaily.sources.push({depot:depotName}); // Only metadata, no PDF references.
        yield {depot:depotName,depotUrl:depot.url,pdfUrl:chosen.url,pdfName:name,snapshot};
      }
    }catch(error){
      allDaily.failures.push({depot:depotName,error:String(error?.message||error)});
    }finally{
      checked++;
      if(announce)rosterSetStatus('Indexing Daily rosters one depot at a time… '+checked+'/'+depots.length);
    }
  }
}
async function rosterReleaseDailySource(source){
  const snap=source?.snapshot;if(!snap)return;
  if(rosterState.pdfDoc===snap.pdfDoc)return; // Do not close the currently opened roster.
  if(rosterPdfMemoryCache.get(source.pdfUrl)===snap)rosterPdfMemoryCache.delete(source.pdfUrl);
  try{await snap.pdfDoc?.destroy()}catch(error){console.debug('Roster PDF cleanup',error)}
  snap.pdfDoc=null;snap.pdfBytes=null;
  if(Array.isArray(snap.pages))snap.pages.length=0;
}
'''
    fn="async function rosterBuildDailyShiftIndex(date,role='Drivers',{announce=false}={}){"
    js=exact(js,fn,helpers+"\n"+fn,"memory helpers")
    before="""  const allDaily=await rosterPreloadAllDailyRosters(date,role,{announce});
  const index={version:1,date,role,generated:Number(rosterState.cacheGenerated||0),createdAt:Date.now(),shifts:{},inactive:{},rows:[],sourceCount:allDaily.sources.length,total:allDaily.total,unavailable:allDaily.failures.length+allDaily.missingDate.length,unavailableDepots:[...allDaily.failures,...allDaily.missingDate].map(entry=>entry.depot).filter(Boolean)};
  let completed=0;
  for(const source of allDaily.sources){
    const strikeCache=new Map();"""
    after="""  const lowMemory=rosterShiftLowMemoryDevice();
  const allDaily=lowMemory?{date,role,sources:[],failures:[],missingDate:[],total:0}
    :await rosterPreloadAllDailyRosters(date,role,{announce});
  const index={version:1,date,role,generated:Number(rosterState.cacheGenerated||0),createdAt:Date.now(),shifts:{},inactive:{},rows:[],sourceCount:allDaily.sources.length,total:allDaily.total,unavailable:allDaily.failures.length+allDaily.missingDate.length,unavailableDepots:[...allDaily.failures,...allDaily.missingDate].map(entry=>entry.depot).filter(Boolean)};
  let completed=0;
  const sourceSequence=lowMemory?rosterDailySourcesLowMemory(date,role,allDaily,{announce}):allDaily.sources;
  for await(const source of sourceSequence){
    const strikeCache=new Map();
    try{"""
    js=exact(js,before,after,"stream per-depot PDFs")
    old=r"    completed\+\+;if\(announce\)rosterSetStatus\([^;\n]*\);\n  \}\n  rosterDailyShiftIndexMemory\.set\(key,index\);"
    aft="""    completed++;if(announce&&!lowMemory)
      rosterSetStatus('Building all-depot Shift index… '+completed+'/'+allDaily.sources.length);
    }finally{
      if(lowMemory){
        for(const info of strikeCache.values()){
          const canvas=info?.canvas;if(canvas){canvas.width=0;canvas.height=0}
        }
        strikeCache.clear();
        await rosterReleaseDailySource(source);
      }
    }
  }
  if(lowMemory){
    index.sourceCount=allDaily.sources.length;
    index.total=allDaily.total;
    index.unavailable=allDaily.failures.length+allDaily.missingDate.length;
    index.unavailableDepots=[...allDaily.failures,...allDaily.missingDate].map(entry=>entry.depot).filter(Boolean);
  }
  rosterDailyShiftIndexMemory.set(key,index);"""
    js=one_regex(js,old,aft,"release each depot snapshot")
    js=exact(js,"""function rosterWarmAllDailyShiftSearch(){
  const date=rosterAdvancedUi.shiftDate?.value||'';""",
       """function rosterWarmAllDailyShiftSearch(){
  if(rosterShiftLowMemoryDevice()){
    if(rosterAdvancedUi.shiftDate?.value)
      rosterSetStatus('Choose a shift and tap Search. Daily rosters will be indexed one depot at a time.');
    return;
  }
  const date=rosterAdvancedUi.shiftDate?.value||'';""","disable background indexing on iPhone")
    js=exact(js,"""  let sprCrew='',sprDuty='',sprEntry=null,sprHasShift=false,sprPdfPrewarm=null;
  try{
    sprEntry=await rosterLoadSprShiftIndex(date,role);""",
       """  let sprCrew='',sprDuty='',sprEntry=null,sprHasShift=false,sprPdfPrewarm=null;
  const lowMemory=rosterShiftLowMemoryDevice();
  if(!lowMemory)try{
    sprEntry=await rosterLoadSprShiftIndex(date,role);""","avoid huge SPR prewarm during iPhone roster search")
    js=exact(js,"const shiftDisplay=sprHasShift?rosterShiftLink(shift,date,role):esc(shift);",
       "const shiftDisplay=(sprHasShift||lowMemory)?rosterShiftLink(shift,date,role):esc(shift);",
       "retain clickable SPR link")
    # Avoid PDF Blob/File/ArrayBuffer duplication when indexing Daily PDFs.
    old=r"    const blob=new Blob\(\[response\.data\],[^\n]*\);\n    const file=new File\([^\n]*\);\n    const bytes=new Uint8Array\(await file\.arrayBuffer\(\)\);\n    const pdfBytes=bytes\.slice\(\)\.buffer;\n    const pdf=await pdfjsLib\.getDocument\(\{data:bytes\}\)\.promise;"
    new="""    const compact=rosterShiftLowMemoryDevice();
    const name=response.filename||(String(label).toLowerCase().endsWith('.pdf')?label:String(label)+'.pdf');
    const bytes=compact?(response.data instanceof Uint8Array?response.data:new Uint8Array(response.data))
      :new Uint8Array(await new File([new Blob([response.data],{type:response.contentType||'application/pdf'})],name,{type:'application/pdf'}).arrayBuffer());
    const pdfBytes=compact?null:bytes.slice().buffer;
    const pdf=await pdfjsLib.getDocument({data:bytes}).promise;"""
    js=one_regex(js,old,new,"avoid duplicate PDF buffer allocations")
    js=exact(js,"const snapshot={name:file.name,pages,pdfDoc:pdf,pdfBytes};",
             "const snapshot={name,pages,pdfDoc:pdf,pdfBytes};",
             "snapshot filename")
    # Context-scoped origin corrections; preserve any already known location.
    before="""  const incomingLocation=r.incomingRelieveLocation||nameOriginLocation||'Not identified';
  const opening=r.incomingRelieveShift"""
    after=r"""  // Original 3/11 Drivers SPR: Fuller relieves 41-B at Sydney Terminal.
  // Sydenham is an adjacent station, not the printed handover point.
  const correctFuller41B=/03_11_2026/i.test(state.fileName||'')&&
    /^driver/i.test(state.role||'')&&/\bFuller\b/i.test(context?.shift?.crew||'')&&
    normaliseRun(r.run||'').replace(/[^0-9A-Z]/gi,'')==='41B'&&
    Boolean(r.incomingRelieveShift);
  let incomingLocation=r.incomingRelieveLocation||nameOriginLocation||'Not identified';
  if(correctFuller41B&&/\bSydenham\b/i.test(incomingLocation))
    incomingLocation='Sydney Terminal';
  const opening=r.incomingRelieveShift"""
    js=exact(js,before,after,"Fuller 41-B relief handover")
    before="""  let crewOriginDisplay=String(crewOrigin||r.nextDuty||'Not identified').trim();"""
    after=r"""  let crewOriginDisplay=String(crewOrigin||r.nextDuty||'Not identified').trim();
  // 3 November Drivers 623G: only repair a missing origin (Bondi Junction).
  if(/03_11_2026/i.test(state.fileName||'')&&/^driver/i.test(state.role||'')&&
      normaliseRun(r.run||'').replace(/[^0-9A-Z]/gi,'')==='623G'&&
      /^Not identified\b/i.test(crewOriginDisplay)){
    const start=normaliseTime(r.runStartTime||r.originTiming?.departureTime||'');
    crewOriginDisplay=['Bondi Junction',start].filter(Boolean).join(' ');
  }"""
    js=exact(js,before,after,"623G run origin")
    before="""  let nameOriginLocation=nameOriginRow?(nameOriginRow.empty?addEmptyMarker(nameOriginRow.location):nameOriginRow.location):(formationLocation||r.incomingRelieveLocation||r.originTiming?.location||dutyLocation(r.nextDuty));"""
    after="""  let nameOriginLocation=nameOriginRow?(nameOriginRow.empty?addEmptyMarker(nameOriginRow.location):nameOriginRow.location):(formationLocation||r.incomingRelieveLocation||r.originTiming?.location||dutyLocation(r.nextDuty));
  if(/03_11_2026/i.test(state.fileName||'')&&/^driver/i.test(state.role||'')&&
     normaliseRun(r.run||'').replace(/[^0-9A-Z]/gi,'')==='623G'&&
     /^Not identified$/i.test(String(nameOriginLocation||'')))
    nameOriginLocation='Bondi Junction';"""
    js=exact(js,before,after,"623G name-search origin")
    return js

def hash256(data):return hashlib.sha256(data).hexdigest()
def site_root():
    p=os.environ['SFTP_ROOT'].replace('\\','/').rstrip('/')
    if p.endswith('/sps/spr'):return p[:-4]
    if p.endswith('/sps'):return p
    if p.endswith('/public_html') or p=='public_html':return p+'/sps'
    raise RuntimeError('Unexpected SFTP site root')
def read(ftp,path):
    with ftp.open(path,'rb') as f:return f.read()
def write(ftp,path,data):
    with ftp.open(path,'wb') as f:
        for i in range(0,len(data),1048576):f.write(data[i:i+1048576])
        f.flush()
def main():
    raw=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode()
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(raw));break
        except Exception:pass
    if key is None:raise RuntimeError('Existing SFTP key unavailable')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ['SFTP_HOST'],username=os.environ['SFTP_USERNAME'],
                pkey=key,port=int(os.environ.get('SFTP_PORT') or 22),
                timeout=12,auth_timeout=12,banner_timeout=12,
                allow_agent=False,look_for_keys=False)
    ftp=ssh.open_sftp()
    root=site_root();originals={};fresh={};staged=[];published=[]
    try:
        old=read(ftp,posixpath.join(root,OLD_JS))
        if not hash256(old).startswith(EXPECTED_JS):
            raise RuntimeError('Live JS checksum unexpected '+hash256(old)[:24]+'; no changes')
        originals['script.js']=read(ftp,posixpath.join(root,'script.js'))
        originals[OLD_JS]=old
        for name in ('index.php','index.html'):
            originals[name]=read(ftp,posixpath.join(root,name))
        fresh[NEW_JS]=patch(old.decode('utf-8')).encode('utf-8')
        if hash256(originals['script.js'])==hash256(old):
            fresh['script.js']=fresh[NEW_JS]
        else:
            print('[MOBILE 224 NOTE] original script.js diverged: keeping it unchanged',flush=True)
        for name in ('index.php','index.html'):
            text=originals[name].decode('utf-8')
            old_import='./'+OLD_JS
            if text.count(old_import)!=1 or 'class="build-number">Build 700' not in text:
                raise RuntimeError('Unexpected HTML module import in '+name)
            fresh[name]=text.replace(old_import,'./'+NEW_JS,1).encode('utf-8')
        try:
            ftp.stat(posixpath.join(root,NEW_JS))
            raise RuntimeError('New asset already exists: refusing overwrite')
        except FileNotFoundError:
            pass
        print('[MOBILE 224 PATCH SOURCE VERIFIED]',hash256(old)[:24],flush=True)
        for name,data in fresh.items():
            target=posixpath.join(root,name)
            temp=target+'.nov3-mobile-stage-'+str(os.getpid())
            write(ftp,temp,data)
            if hash256(read(ftp,temp))!=hash256(data):
                raise RuntimeError('Staged file SHA mismatch '+name)
            ftp.chmod(temp,0o644)
            staged.append((name,target,temp))
        try:
            names=[NEW_JS]+(['script.js'] if 'script.js' in fresh else [])+['index.php','index.html']
            lookup={n:(t,tmp) for n,t,tmp in staged}
            for name in names:
                target,temp=lookup[name]
                ftp.posix_rename(temp,target)
                published.append(name)
                if hash256(read(ftp,target))!=hash256(fresh[name]):
                    raise RuntimeError('Live file SHA mismatch '+name)
                print('[MOBILE 224 PATCH LIVE VERIFIED]',name,hash256(fresh[name])[:16],flush=True)
            print('[MOBILE 224 PATCH COMPLETE] Serial iPhone index; 623G Bondi Junction; Fuller 41-B Sydney Terminal; source PDFs unchanged',flush=True)
        except Exception:
            for name in reversed(published):
                target=posixpath.join(root,name)
                if name==NEW_JS:ftp.remove(target)
                else:
                    tmp=target+'.nov3-mobile-rollback-'+str(os.getpid())
                    write(ftp,tmp,originals[name])
                    ftp.posix_rename(tmp,target)
                print('[MOBILE 224 PATCH ROLLBACK]',name,flush=True)
            raise
    finally:
        for name,target,temp in staged:
            try:ftp.remove(temp)
            except Exception:pass
        ftp.close();ssh.close()

if __name__=='__main__':main()
