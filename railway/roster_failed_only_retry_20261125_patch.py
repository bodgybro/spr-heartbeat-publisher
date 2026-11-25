#!/usr/bin/env python3
"""Resume incomplete roster updates without redownloading verified files.
Preserve the original download, archive, dual-site and manifest pipeline.
Checkpoint is private, per Sydney scheduled slot, and survives restarts.
"""
import ast
from pathlib import Path
import sys
MARKER="# ROSTER_FAILED_ONLY_RETRY_20261125_V1"
HELPERS=r'''
# ROSTER_FAILED_ONLY_RETRY_20261125_V1
import threading as _rr_threading
_RR_TLS=_rr_threading.local()
_RR_SYNC_ORIGINAL=sync_all_rosters_online
_RR_STORE_ORIGINAL=_store_roster_fast

def _rr_path():
    return DATA_ROOT/".roster-failed-only-checkpoint-v1.json"

def _rr_slot():
    from datetime import datetime,timedelta
    from zoneinfo import ZoneInfo
    now=datetime.now(ZoneInfo("Australia/Sydney"))
    slots=[now.replace(hour=h,minute=0,second=0,microsecond=0) for h in (8,12,16,22)]
    earlier=[x for x in slots if x<=now]
    return (max(earlier) if earlier else slots[-1]-timedelta(days=1)).isoformat()

def _rr_valid_row(row):
    import re
    try:
        _roster_valid_cache_path(row["path"])
        _roster_sftp_check_url(row["url"])
        return (isinstance(row["size"],int) and row["size"]>=100 and
                bool(re.fullmatch(r"[0-9a-f]{64}",row["sha"])))
    except Exception:return False

def _rr_load(slot):
    import json
    try:
        p=_rr_path()
        if p.stat().st_size>500000:return {}
        raw=json.loads(p.read_text(encoding="utf-8"))
        rows=raw.get("rows")
        if raw.get("slot")!=slot or not isinstance(rows,dict) or len(rows)>78:return {}
        return {k:r for k,r in rows.items() if isinstance(r,dict) and k==r.get("path") and _rr_valid_row(r)}
    except Exception:return {}

def _rr_save():
    import json,os,tempfile
    if not getattr(_RR_TLS,"active",False):return
    p=_rr_path()
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=p.parent,prefix=".roster-retry-",delete=False) as f:
            temp=f.name
            os.chmod(temp,0o600)
            json.dump({"slot":_RR_TLS.slot,"rows":_RR_TLS.rows},f,separators=(",",":"))
            f.flush();os.fsync(f.fileno())
        os.replace(temp,p)
    except Exception as exc:
        print("[ROSTER RETRY CHECKPOINT DEFERRED] "+type(exc).__name__,flush=True)
    finally:
        if temp and os.path.exists(temp):
            try:os.unlink(temp)
            except OSError:pass

def _rr_remote_verify(ssh,root,rows):
    # One server-side SHA batch per site, no download of successful PDFs.
    import shlex,re
    paths={root.rstrip("/")+"/rosters/"+r["path"]:r for r in rows.values()}
    if not paths:return set()
    cmd="sha256sum -- "+" ".join(shlex.quote(p) for p in paths)
    stdin,stdout,stderr=ssh.exec_command(cmd,timeout=45)
    try:
        stdout.channel.settimeout(90)
        raw=stdout.read(100000).decode("utf-8","replace")
        stdout.channel.recv_exit_status()
    finally:
        stdin.close();stdout.close();stderr.close()
    valid=set()
    for line in raw.splitlines():
        m=re.fullmatch(r"([0-9a-f]{64})  (.+)",line)
        if m and m[2] in paths and m[1]==paths[m[2]]["sha"]:
            valid.add(paths[m[2]]["path"])
    return valid

def _rr_validate_checkpoint():
    # Close the borrowed connections in the original sync finally handlers.
    if not _RR_TLS.rows:return
    try:
        ssh,ftp,root=_roster_sftp_connection()
        primary=_rr_remote_verify(ssh,root,_RR_TLS.rows)
        ssh,ftp=_dual_connection()
        secondary=_rr_remote_verify(ssh,_DUAL_KUSTOM_ROOT,_RR_TLS.rows)
        valid=primary&secondary
        _RR_TLS.rows={k:r for k,r in _RR_TLS.rows.items() if k in valid}
        _RR_TLS.reusable=set(_RR_TLS.rows)
    except Exception as exc:
        # If either host cannot authenticate a checkpoint, re-download;
        # never count an unverified file as a success.
        print("[ROSTER RETRY CHECKPOINT VERIFY DEFERRED] "+type(exc).__name__,flush=True)
        _RR_TLS.rows={}
        _RR_TLS.reusable=set()
        try:_roster_sftp_release()
        except Exception:pass
        try:_dual_release_connection()
        except Exception:pass
    _rr_save()

def _rr_reuse(url,name,path):
    if not getattr(_RR_TLS,"active",False):return False
    if not getattr(_RR_TLS,"validated",False):
        _RR_TLS.validated=True
        _rr_validate_checkpoint()
        print("[ROSTER RETRY PLAN] "+str(len(_RR_TLS.reusable))+" verified PDFs skipped; remaining files only",flush=True)
    row=_RR_TLS.rows.get(path)
    if path not in _RR_TLS.reusable or not row or row["url"]!=url or name!=path.rsplit("/",1)[-1]:
        return False
    # Rehydrate only the proof independently verified against both current
    # copies this attempt. The unchanged manifest validator still runs.
    _DUAL_SITE_ROSTER_TLS.proofs[url]=(path,row["size"],row["sha"])
    _RR_TLS.skipped+=1
    print("    [ROSTER RETRY SKIP VERIFIED] "+path,flush=True)
    return True

def _store_roster_fast(pdf_url,pdf_name,data,cache_path):
    import hashlib
    active=getattr(_RR_TLS,"active",False)
    if active:
        # A newly attempted file is not reusable until both stores verify.
        _RR_TLS.rows.pop(cache_path,None);_RR_TLS.reusable.discard(cache_path)
        _rr_save()
        issues=getattr(_DUAL_SITE_ROSTER_TLS,"issues",{})
        before={k:len(v) for k,v in issues.items()}
    result=_RR_STORE_ORIGINAL(pdf_url,pdf_name,data,cache_path)
    if active:
        issues=getattr(_DUAL_SITE_ROSTER_TLS,"issues",{})
        unchanged=all(len(v)==before.get(k,0) for k,v in issues.items())
        proof=getattr(_DUAL_SITE_ROSTER_TLS,"proofs",{}).get(pdf_url)
        digest=hashlib.sha256(data).hexdigest()
        if unchanged and proof==(cache_path,len(data),digest):
            row={"path":cache_path,"url":pdf_url,"size":len(data),"sha":digest}
            if _rr_valid_row(row):
                _RR_TLS.rows[cache_path]=row
                _rr_save()
    return result

def sync_all_rosters_online():
    if not _dual_enabled():return _RR_SYNC_ORIGINAL()
    slot=_rr_slot()
    _RR_TLS.active=True;_RR_TLS.slot=slot;_RR_TLS.rows=_rr_load(slot)
    _RR_TLS.reusable=set();_RR_TLS.validated=False;_RR_TLS.skipped=0
    try:
        result=_RR_SYNC_ORIGINAL()
        if isinstance(result,dict):
            result["files_reused"]=_RR_TLS.skipped
            if result.get("ok") is True:
                _rr_path().unlink(missing_ok=True)
                print("[ROSTER RETRY COMPLETE] verified all roster PDFs; reused="+str(_RR_TLS.skipped),flush=True)
            else:
                _rr_save()
                print("[ROSTER RETRY PENDING] verified checkpoint="+str(len(_RR_TLS.rows)),flush=True)
        return result
    finally:
        _RR_TLS.active=False
'''
def apply(path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:return
    for token in ("# SPR_VERIFIED_COMPLETION_REPORTING","_DUAL_SITE_ROSTER_TLS.proofs","_DUAL_SITE_ROSTER_TLS.issues","def _roster_sftp_connection(","def _dual_connection("):
        if token not in source:raise RuntimeError("Missing verified updater hook: "+token)
    tree=ast.parse(source)
    base=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="sync_all_rosters_online" and "pdf_count" in (ast.get_source_segment(source,n) or "")]
    if len(base)!=1:raise RuntimeError("Expected one actual roster download loop")
    node=base[0];lines=source.splitlines(keepends=True);block="".join(lines[node.lineno-1:node.end_lineno])
    # Only replace the normal attempt, not the existing browser recovery
    # branch. All existing entries, success accounting and error handling stay.
    old="                            data=_download_roster_pdf_fast(page,pdf_url,pdf_name)\n                            _store_roster_fast(pdf_url,pdf_name,data,cache_path)"
    new="                            if not _rr_reuse(pdf_url,pdf_name,cache_path):\n                                data=_download_roster_pdf_fast(page,pdf_url,pdf_name)\n                                _store_roster_fast(pdf_url,pdf_name,data,cache_path)"
    if block.count(old)!=1:raise RuntimeError("Expected exact primary roster download pair")
    block=block.replace(old,new,1)
    # Retain the original counter as total verified, distinguish actual
    # downloads in summary and telemetry.
    old='msg=f"{pdf_count}/{expected} roster PDFs downloaded and stored across {len(depots)} depots"'
    new='msg=f"{pdf_count}/{expected} roster PDFs verified across {len(depots)} depots ({getattr(_RR_TLS,\'skipped\',0)} reused, {pdf_count-getattr(_RR_TLS,\'skipped\',0)} downloaded and stored)"'
    if block.count(old)!=1:raise RuntimeError("Expected verified completion message")
    block=block.replace(old,new,1)
    # The actual downloader count is independent of verified count.
    old='"files_downloaded":pdf_count,"files_uploaded":pdf_count'
    new='"files_downloaded":pdf_count-getattr(_RR_TLS,\'skipped\',0),"files_uploaded":pdf_count'
    if block.count(old)!=1:raise RuntimeError("Expected completion counters")
    block=block.replace(old,new,1)
    source="".join(lines[:node.lineno-1])+block.rstrip()+"\n"+"".join(lines[node.end_lineno:])
    tree=ast.parse(source)
    mains=[n for n in tree.body if isinstance(n,ast.If) and "__name__" in (ast.get_source_segment(source,n.test) or "")]
    if len(mains)!=1:raise RuntimeError("Expected unique updater entrypoint")
    lines=source.splitlines(keepends=True);i=mains[0].lineno-1
    source="".join(lines[:i])+HELPERS+"\n"+"".join(lines[i:])
    compile(source,str(path),"exec")
    path.write_text(source,encoding="utf-8")
    print("ROSTER_FAILED_ONLY_RETRY_READY slot_checkpoint=yes dual_SHA=yes full_manifest=yes",flush=True)
if __name__=="__main__":apply(Path(sys.argv[1]))
