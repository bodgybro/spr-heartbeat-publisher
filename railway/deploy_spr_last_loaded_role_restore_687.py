#!/usr/bin/env python3
"""SFTP-only: restore last successfully loaded SPR date+role on reload (Build 687 frontend).
Do not modify source SPRs, indexes, roster data, Railway updater, credentials or RC1 backup.
"""
import os,io,base64,posixpath,hashlib
import paramiko

PREFIX={
 "script.js":"333e3ee873a34f62",
 "index.php":"3bf6e558b29ac59f",
 "index.html":"f21d786d293b8214"
}
OLD_BOOT="""function scheduleRetainedSprRestore(){
  const initialSerial=sprLoadSerial;
  const run=()=>{if(initialSerial!==sprLoadSerial||state.pages.length||ui.onlineLoad.disabled)return;
    restoreRetainedSpr().catch(error=>console.warn('Retained SPR restore failed',error));};
  if('requestIdleCallback' in window)requestIdleCallback(run,{timeout:1200});
  else setTimeout(run,0);
}
"""
NEW_BOOT="""// Restore the last LOADED selection, not the newest delayed IndexedDB write.
// Driver and Guard caches are separate; newest savedAt is not user intent.
function scheduleRetainedSprRestore(){
  const initialSerial=sprLoadSerial;
  const stillInitial=()=>initialSerial===sprLoadSerial&&!state.pages.length&&!ui.onlineLoad.disabled;
  const run=async()=>{
    if(!stillInitial()||window.__SPR_PREINDEX_MODE||new URLSearchParams(location.search).has('spr_preindex'))return;
    let preferred=null;
    try{
      const meta=JSON.parse(localStorage.getItem('sprRetainedMeta')||'null');
      if(meta&&/^\\d{4}-\\d{2}-\\d{2}$/.test(meta.date)&&['driver','guard'].includes(meta.role))
        preferred={date:meta.date,role:meta.role};
    }catch(_){}
    try{
      if(preferred){
        // Use the exact date and role the user last successfully loaded.
        const cached=await readRetainedSpr(preferred.date,preferred.role).catch(()=>null);
        if(!stillInitial())return;
        if(cached?.pages?.length&&sprSelectionMatches(cached,preferred.date,preferred.role)&&
          !sprPagesConflictWithRole(cached.pages,preferred.role)&&
          cached.parserBuild===SPR_PARSER_BUILD&&cached.pageLayoutBuild===SPR_PAGE_LAYOUT_BUILD){
          if(await restoreRetainedSpr(cached))return;
          if(!stillInitial())return;
        }
        // Last loaded index can precede its deferred IndexedDB save.
        // Fetch the fast prepared server index for that selection; never
        // restore another role merely because that old cache wrote later.
        if(stillInitial()){
          ui.date.value=preferred.date;
          ui.role.value=preferred.role;
          await loadOnlinePdf();
        }
        return;
      }
      // Backwards compatibility for devices without selection metadata.
      const legacy=await readRetainedSpr();
      if(stillInitial()&&legacy?.pages?.length&&
          sprSelectionMatches(legacy,legacy.date,legacy.role)&&
          !sprPagesConflictWithRole(legacy.pages,legacy.role))
        await restoreRetainedSpr(legacy);
    }catch(error){console.warn('Retained SPR restore failed',error)}
  };
  if('requestIdleCallback' in window)requestIdleCallback(run,{timeout:1200});
  else setTimeout(run,0);
}
"""
OLD_META="    localStorage.setItem('sprRetainedMeta',JSON.stringify({date:payload.date,role:payload.role,fileName:payload.fileName,savedAt:payload.savedAt}));"
NEW_META="""    // Do not let an older deferred write overwrite the user's new selection.
    if(state.loadedDate===payload.date&&state.role===payload.role)
      localStorage.setItem('sprRetainedMeta',JSON.stringify({date:payload.date,role:payload.role,fileName:payload.fileName,savedAt:payload.savedAt}));"""
OLD_CACHE="script.js?v=687-standby-order"
NEW_CACHE="script.js?v=687-retain-last-spr"

def sha(b):return hashlib.sha256(b).hexdigest()
def remote_root():
    root=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
    if root.endswith("/sps/spr"):return root[:-4]
    if root.endswith("/sps"):return root
    if root.endswith("/public_html") or root=="public_html":return root+"/sps"
    raise RuntimeError("Unexpected SFTP web root")
def read(sftp,p):
    with sftp.open(p,"rb") as f:return f.read()
def save(sftp,p,data):
    with sftp.open(p,"wb") as f:f.write(data)
def patch_js(t):
    anchor="function scheduleRetainedSprRestore(){"
    after="if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',scheduleRetainedSprRestore"
    if t.count(anchor)!=1 or t.count(after)!=1:
        raise RuntimeError("Expected one existing page-reload restore function and handler")
    a=t.index(anchor); b=t.index(after,a)
    current=t[a:b]
    if not (0<len(current)<5000 and "restoreRetainedSpr().catch" in current and
            "sprLoadSerial" in current and "requestIdleCallback" in current):
        raise RuntimeError("Existing bootstrap has unfamiliar behaviour; refusing")
    if "async function sprOriginalPdfMatchesIndex(buffer)" not in t:
        raise RuntimeError("Working Build 687 original PDF SHA safeguard missing")
    if "order:Number.isFinite(standby._startIndex)" not in t:
        raise RuntimeError("Working Shift 53 standby-order fix missing")
    t=t[:a]+NEW_BOOT+t[b:]
    if t.count(OLD_META)==1:
        t=t.replace(OLD_META,NEW_META,1)
    else:
        raise RuntimeError("Cache metadata writer changed; refusing patch")
    return t
def patch_html(t,name):
    if t.count(OLD_CACHE)!=1:raise RuntimeError("Unexpected cache reference in "+name)
    if 'class="build-number">Build 687' not in t:raise RuntimeError("Live Build 687 label mismatch")
    return t.replace(OLD_CACHE,NEW_CACHE,1)
def main():
    keytext=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode()
    key=None
    for kind in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=kind.from_private_key(io.StringIO(keytext));break
        except Exception:pass
    if key is None:raise RuntimeError("Configured SFTP key invalid")
    ssh=paramiko.SSHClient()
    ssh.load_host_keys("/data/credentials/spr-sftp-known_hosts")
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ["SFTP_HOST"],username=os.environ["SFTP_USERNAME"],
      port=int(os.environ.get("SFTP_PORT") or 22),pkey=key,
      look_for_keys=False,allow_agent=False,timeout=12,auth_timeout=12,banner_timeout=12)
    ftp=ssh.open_sftp();root=remote_root()
    original={};new={};staged=[];applied=[]
    try:
        for n in ("script.js","index.php","index.html"):
            original[n]=read(ftp,posixpath.join(root,n))
            current_sha=sha(original[n])
            if not current_sha.startswith(PREFIX[n]):
                raise RuntimeError(n+" no longer matches tested live 687 file; refusing: "+current_sha[:16])
            t=original[n].decode("utf-8")
            modified=patch_js(t) if n=="script.js" else patch_html(t,n)
            new[n]=modified.encode("utf-8")
            if new[n]==original[n]:raise RuntimeError("No change for "+n)
        # Preflight every change before touching any live destination.
        compile_check=new["script.js"].decode("utf-8")
        if NEW_BOOT not in compile_check or "sprRetainedMeta" not in compile_check:
            raise RuntimeError("JS preflight failed")
        for n,data in new.items():
            dest=posixpath.join(root,n);tmp=dest+".lastspr-stage-"+str(os.getpid())
            save(ftp,tmp,data)
            if sha(read(ftp,tmp))!=sha(data):raise RuntimeError("Staging checksum mismatch "+n)
            staged.append((n,tmp,dest))
        try:
            for n,tmp,dest in staged:
                ftp.posix_rename(tmp,dest);applied.append(n)
                if sha(read(ftp,dest))!=sha(new[n]):raise RuntimeError("Live checksum mismatch "+n)
                print("[LAST SPR LIVE VERIFIED]",n,sha(new[n])[:16],flush=True)
            print("[LAST SPR RESTORE COMPLETE] Date and role retained; Build 687 label, original PDF viewer, RC1 untouched",flush=True)
        except Exception:
            for n in reversed(applied):
                dest=posixpath.join(root,n);tmp=dest+".lastspr-rollback-"+str(os.getpid())
                save(ftp,tmp,original[n]);ftp.posix_rename(tmp,dest)
                print("[LAST SPR ROLLBACK]",n,flush=True)
            raise
    finally:
        for _,tmp,_ in staged:
            try:ftp.remove(tmp)
            except Exception:pass
        ftp.close();ssh.close()
if __name__=="__main__":main()
