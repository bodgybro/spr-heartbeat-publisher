#!/usr/bin/env python3
"""Build 700 live SPR Search: order identical-run cards by actual run start.

Read/patch only public script.js, index.php and index.html using existing
verified SFTP; no roster files, SPR PDFs, indices, auth, parsing or updater edits.
Uses exact live SHA guards and reversible staged writes.
"""
import os,io,base64,posixpath,re,hashlib
from pathlib import Path
import paramiko

EXPECTED={
    "script.js":"a97d6d4707a40cea8fe63ea142236172",
    "index.php":"4dc177dcc4d42267bc8b06674e7c316e",
    "index.html":"54f2f59f3acb3fefaa47a6715d875745",
}
VERSION="700-chrono-run-start-20261101"
MARKER="// SPR_SORT_RUN_START_20261101"
OLD=r"""function recordTime(record){
  const match=semanticText(record.nextDuty||'').match(/\b([0-2]\d[0-5]\d)\b/);
  if(!match)return Number.POSITIVE_INFINITY;
  return Number(match[1].slice(0,2))*60+Number(match[1].slice(2));
}"""
NEW=r"""function recordTime(record){
  // SPR_SORT_RUN_START_20261101
  // Use the actual start of this crew's run, not the first incidental time
  // in the next-duty text (which may refer to a later relief or formed run).
  // 01/11 Guards 568B: Shift 8911 0635 must precede Shift 8066 0711.
  const candidates=[
    record?.runStartTime,
    record?.originTiming?.departureTime,
    record?.incomingRelieveTime,
    record?.originTiming?.arrivalTime
  ];
  for(const candidate of candidates){
    const value=minutesFromTime(normaliseTime(candidate||''));
    if(Number.isFinite(value))return value;
  }
  // Old indexes may omit structured run-start fields.
  const match=semanticText(record?.nextDuty||'').match(/\b((?:[01]\d|2[0-3])[0-5]\d)\b/);
  if(!match)return Number.POSITIVE_INFINITY;
  return Number(match[1].slice(0,2))*60+Number(match[1].slice(2));
}"""

def sha(data):return hashlib.sha256(data).hexdigest()
def remote_root():
    root=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
    if root.endswith("/sps/spr"):return root[:-4]
    if root.endswith("/sps"):return root
    if root.endswith("/public_html") or root=="public_html":return root+"/sps"
    raise RuntimeError("Unexpected SFTP root, no site writes")
def fetch(sftp,path):
    with sftp.open(path,"rb") as handle:return handle.read()
def put(sftp,path,data):
    with sftp.open(path,"wb") as handle:
        for offset in range(0,len(data),1024*1024):
            handle.write(data[offset:offset+1024*1024])
        handle.flush()
def patch_js(text):
    if MARKER in text:return text
    if text.count(OLD)!=1:
        raise RuntimeError("Run-time comparator is not the inspected Build 700 source; no writes")
    required=(
       "function searchRun(value){",
       "function chronologicalRecordAnchor(records){",
       "function chronologicalRecordValue(record,anchor){",
       "function sprOriginalPdfMatchesIndex(",
       "function scheduleRetainedSprRestore()",
       "function verifiedThroughRunDestination(",
       "function recoveredFormedRunOrigin("
    )
    if any(r not in text for r in required):
        raise RuntimeError("Required fast SPR search and SHA guards missing; no writes")
    # The existing comparator already uses chronologicalRecordValue and
    # its midnight rollover anchor; change only the record's time source.
    if text.count("matches.sort((a,b)=>chronologicalRecordValue(a,anchor)-chronologicalRecordValue(b,anchor)")!=1:
        raise RuntimeError("Expected run-search chronological comparator missing; no writes")
    return text.replace(OLD,NEW,1)
def patch_shell(text,name):
    if "class=\"build-number\">Build 700" not in text:
        raise RuntimeError("Unexpected "+name+" build label")
    replaced,count=re.subn(r"script\.js\?v=[A-Za-z0-9_.-]+",
                            "script.js?v="+VERSION,text)
    if count<1 or count>8:
        raise RuntimeError("Unexpected cache version references in "+name)
    return replaced
def main():
    raw=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode("utf-8")
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(raw));break
        except Exception:pass
    if key is None:raise RuntimeError("Existing SFTP private key unavailable")
    ssh=paramiko.SSHClient()
    ssh.load_host_keys("/data/credentials/spr-sftp-known_hosts")
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ["SFTP_HOST"],username=os.environ["SFTP_USERNAME"],
                port=int(os.environ.get("SFTP_PORT") or 22),
                pkey=key,allow_agent=False,look_for_keys=False,
                timeout=12,auth_timeout=12,banner_timeout=12)
    ftp=ssh.open_sftp()
    root=remote_root()
    originals={};patched={};stage=[];replaced=[]
    try:
        for name in ("script.js","index.php","index.html"):
            remote=posixpath.join(root,name)
            old=fetch(ftp,remote)
            text=old.decode("utf-8")
            already=MARKER in text if name=="script.js" else ("script.js?v="+VERSION in text)
            if not already and not sha(old).startswith(EXPECTED[name]):
                raise RuntimeError("Live "+name+" checksum unexpected "+sha(old)[:16]+"; no changes made")
            originals[name]=old
            patched[name]=(patch_js(text) if name=="script.js" else patch_shell(text,name)).encode("utf-8")
            print("[RUN SORT SOURCE]",name,sha(old)[:16],"=>",sha(patched[name])[:16],flush=True)
        if all(patched[name]==originals[name] for name in originals):
            print("[RUN SORT ALREADY INSTALLED] No site files modified",flush=True)
            return
        # Verify all three changes are prepared before changing anything live.
        for name,data in patched.items():
            if data==originals[name]:continue
            remote=posixpath.join(root,name)
            temp=remote+".run-sort-stage-"+str(os.getpid())
            put(ftp,temp,data)
            if sha(fetch(ftp,temp))!=sha(data):
                raise RuntimeError("Staged SHA-256 validation failed: "+name)
            stage.append((name,temp,remote))
        try:
            for name,temp,remote in stage:
                ftp.posix_rename(temp,remote)
                replaced.append(name)
                if sha(fetch(ftp,remote))!=sha(patched[name]):
                    raise RuntimeError("Published SHA-256 validation failed: "+name)
                print("[RUN SORT LIVE VERIFIED]",name,sha(patched[name])[:16],flush=True)
            print("[RUN SORT COMPLETE] Sorted by real run starts; 01/11 Guards 568B 0635 before 0711. PDFs, indexes and rosters untouched.",flush=True)
        except Exception:
            for name in reversed(replaced):
                remote=posixpath.join(root,name)
                backup=remote+".run-sort-rollback-"+str(os.getpid())
                put(ftp,backup,originals[name])
                ftp.posix_rename(backup,remote)
                print("[RUN SORT ROLLBACK]",name,flush=True)
            raise
    finally:
        for name,temp,_ in stage:
            try:ftp.remove(temp)
            except Exception:pass
        ftp.close();ssh.close()

if __name__=="__main__":
    main()
