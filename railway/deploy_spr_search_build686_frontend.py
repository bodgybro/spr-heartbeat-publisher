#!/usr/bin/env python3
"""Deploy only SPR Search Build 686 frontend, using existing Railway SFTP settings.
Run after other updater patches, before start.sh. Does not touch SPRs or rosters.
"""
import os,base64,io,posixpath,hashlib,sys,time
from pathlib import Path
import paramiko

EXPECT={
"script.js":("543674eec7390ae292efd799f1e09a372eaa47df1e9d038908872ba73d540e66","d2c3b0bf5cb87faa8b592856d145f23fc2a1ca4e2f8a0f70af14cd42c6a02556"),
"index.php":("7fe47649fdda8eae9d4587314b1352d4217d54d455711e216c1631b0d340ad04","317d0ffd6695c5df1d3b4fde746b95cf0e1430f96f977773777ad7f10ee67122"),
"index.html":("c2f1d3e840bf740f818662c5939ba0e375cb45a7ec271863fd2751133870cf87","d6aeef537362d791658fb62c3fac8c2229a78c7496c2d12b711421dba34ba868")
}
HELPER="""// Build 686: date and role are a single immutable selection. Never present
// results from another selection, including a restored or published index.
function sprSelectionFilename(date,role){
  const [year,month,day]=String(date||'').split('-');
  return `All ${role==='guard'?'Guards':'Drivers'} Combined ${day}_${month}_${year}.pdf`;
}
function sprSelectionMatches(payload,date,role){
  if(!payload||payload.date!==date||payload.role!==role)return false;
  const expected=sprSelectionFilename(date,role);
  if(payload.fileName&&payload.fileName!==expected)return false;
  if(payload.sourceUrl){
    try{
      const path=decodeURIComponent(new URL(payload.sourceUrl,document.baseURI).pathname);
      if(!path.endsWith('/spr/'+(role==='guard'?'g':'d')+'/'+expected))return false;
    }catch(_){return false}
  }
  return true;
}
function sprPagesConflictWithRole(pages,role){
  let drivers=0,guards=0;
  for(const page of (pages||[]).slice(0,30)){
    const t=String(page.text||'');
    if(/Sydney Trains Driver\\b/i.test(t))drivers++;
    if(/Sydney Trains Guard\\b/i.test(t))guards++;
  }
  return role==='guard'?drivers>0&&guards===0:guards>0&&drivers===0;
}
let sprLoadSerial=0;
function invalidateSprOnSelectorChange(){
  // Cancel queued restores and old in-flight pre-index results.
  sprLoadSerial++;
  if(state.pages.length && (state.loadedDate!==ui.date.value||state.role!==ui.role.value)){
    // Cached bytes are already saved on Load; preserve the existing per-role
    // IndexedDB entry while clearing the active (wrong-role) search results.
    reset();
    setStatus('SPR selection changed. Press Load to open the selected '+(ui.role.value==='guard'?'Guards':'Drivers')+' PDF.','info');
  }
}
ui.role.addEventListener('change',invalidateSprOnSelectorChange);
ui.date.addEventListener('change',invalidateSprOnSelectorChange);
"""
def repl(t,a,b,label):
    if t.count(a)!=1: raise RuntimeError("Build 684 source mismatch: "+label)
    return t.replace(a,b)
def transform(n,t):
    if n!="script.js":
        t=repl(t,"script.js?v=684","script.js?v=686","cache version")
        return repl(t,'class="build-number">Build 684','class="build-number">Build 686',"build label")
    t=repl(t,"async function loadOnlinePdf(){",HELPER+"async function loadOnlinePdf(){","helper")
    t=repl(t,"  const selectedDate=ui.date.value,selectedRole=ui.role.value;\n",
        "  const selectedDate=ui.date.value,selectedRole=ui.role.value;\n  const loadSerial=++sprLoadSerial;\n  const sameSelection=()=>loadSerial===sprLoadSerial&&ui.date.value===selectedDate&&ui.role.value===selectedRole;\n","serial")
    t=repl(t,"      if(cached?.pages?.length&&cached.parserBuild===SPR_PARSER_BUILD&&cached.pageLayoutBuild===SPR_PAGE_LAYOUT_BUILD){",
        "      if(!sameSelection())return;\n      if(cached?.pages?.length&&sprSelectionMatches(cached,selectedDate,selectedRole)&&!sprPagesConflictWithRole(cached.pages,selectedRole)&&cached.parserBuild===SPR_PARSER_BUILD&&cached.pageLayoutBuild===SPR_PAGE_LAYOUT_BUILD){","cached")
    t=repl(t,"        const remoteSha=await publishedIndexSha(selectedDate,selectedRole);",
        "        const remoteSha=await publishedIndexSha(selectedDate,selectedRole);\n        if(!sameSelection())return;","sha")
    t=repl(t,"        const prebuilt=await loadPublishedSprIndex(selectedDate,selectedRole);",
        "        const prebuilt=await loadPublishedSprIndex(selectedDate,selectedRole);\n        if(!sameSelection())return;","prebuilt")
    t=repl(t,"        if(prebuilt){\n          prebuilt.fileName=filename;",
        "        if(prebuilt){\n          if(!sprSelectionMatches({...prebuilt,fileName:filename},selectedDate,selectedRole)||sprPagesConflictWithRole(prebuilt.pages,selectedRole))throw new Error('Published SPR index contains data for the wrong role');\n          prebuilt.fileName=filename;","prebuilt role")
    t=repl(t,"    await loadPdf(new File([buffer],filename,{type:'application/pdf'}),url,selectedDate);",
        "    if(!sameSelection())return;\n    await loadPdf(new File([buffer],filename,{type:'application/pdf'}),url,selectedDate);","pdf")
    t=repl(t,"  if(!cached||!Array.isArray(cached.pages)||!cached.pages.length)return false;",
        "  if(!cached||!Array.isArray(cached.pages)||!cached.pages.length)return false;\n  if(!sprSelectionMatches(cached,cached.date,cached.role)||sprPagesConflictWithRole(cached.pages,cached.role))return false;","restore")
    t=repl(t,"  const run=()=>restoreRetainedSpr().catch(error=>console.warn('Retained SPR restore failed',error));",
        "  const initialSerial=sprLoadSerial;\n  const run=()=>{if(initialSerial!==sprLoadSerial||state.pages.length||ui.onlineLoad.disabled)return;\n    restoreRetainedSpr().catch(error=>console.warn('Retained SPR restore failed',error));};","startup")
    return t
def sha(b): return hashlib.sha256(b).hexdigest()
def main():
    root=os.environ["SFTP_ROOT"].rstrip("/")
    if root.endswith("/sps/spr"): root=root[:-4]
    elif root.endswith("/public_html") or root=="public_html":root+="/sps"
    elif not root.endswith("/sps"):raise RuntimeError("Unexpected SFTP root suffix")
    kh=Path("/data/credentials/spr-sftp-known_hosts")
    keytext=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode()
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(keytext));break
        except Exception:pass
    if key is None:raise RuntimeError("Unable to parse configured SFTP key")
    ssh=paramiko.SSHClient()
    if kh.exists():ssh.load_host_keys(str(kh))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ["SFTP_HOST"],port=int(os.environ.get("SFTP_PORT","22")),
                username=os.environ["SFTP_USERNAME"],pkey=key,look_for_keys=False,allow_agent=False,timeout=12)
    s=ssh.open_sftp()
    try:
        originals={};updated={}
        for n,hashes in EXPECT.items():
            with s.open(posixpath.join(root,n),"rb") as f:old=f.read()
            if sha(old)==hashes[1]:
                print("[BUILD 686 ALREADY PRESENT]",n,flush=True);continue
            if sha(old)!=hashes[0]:raise RuntimeError("Live SHA mismatch for "+n+"; no files changed")
            new=transform(n,old.decode()).encode()
            if sha(new)!=hashes[1]:raise RuntimeError("Patch SHA mismatch for "+n+"; no files changed")
            originals[n]=old;updated[n]=new
        if not updated:return
        # Stage and verify ALL files first, then replace atomically one by one.
        staged=[]
        for n,content in updated.items():
            dest=posixpath.join(root,n);temp=dest+".b686-"+str(os.getpid())
            with s.open(temp,"wb") as f:f.write(content)
            with s.open(temp,"rb") as f:verify=f.read()
            if sha(verify)!=EXPECT[n][1]:raise RuntimeError("Staging failed "+n)
            staged.append((n,temp,dest))
        completed=[]
        try:
            for n,temp,dest in staged:
                s.posix_rename(temp,dest)
                with s.open(dest,"rb") as f:verify=f.read()
                if sha(verify)!=EXPECT[n][1]:raise RuntimeError("Verification failed "+n)
                completed.append(n)
                print("[BUILD 686 LIVE VERIFIED]",n,flush=True)
        except Exception:
            for n in reversed(completed):
                dest=posixpath.join(root,n)
                with s.open(dest,"wb") as f:f.write(originals[n])
                print("[BUILD 686 ROLLED BACK]",n,flush=True)
            raise
    finally:s.close();ssh.close()
if __name__=="__main__":main()
