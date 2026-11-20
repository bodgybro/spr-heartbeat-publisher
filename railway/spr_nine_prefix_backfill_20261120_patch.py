#!/usr/bin/env python3
"""One-time source-hash-verified reindex of ALL available dated SPR PDFs.

Safely extends the already-running direct original-PDF publisher. Uses the
existing verified primary/secondary upload, primary source SHA check and
Kustom-only private SQLite follow-up; no new GitHub Actions or cPanel cron.
"""
import ast
from pathlib import Path
import sys

MARKER = "# SPR_ALL_NINE_SHIFT_PREFIXES_BACKFILL_20261120"

EXTENSION = r'''
# SPR_ALL_NINE_SHIFT_PREFIXES_BACKFILL_20261120
def _spr_nine_prefix_backfill():
    import datetime as _np_datetime
    import hashlib as _np_hashlib
    import os as _np_os
    import pathlib as _np_pathlib
    import re as _np_re
    import shlex as _np_shlex
    import time as _np_time
    from zoneinfo import ZoneInfo as _np_ZoneInfo
    marker_dir=_np_pathlib.Path("/data/spr-nine-prefix-backfill-20261120")
    marker_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    print("[SPR NINE PREFIX BACKFILL] Discovering original dated PDFs; original upload schedules unchanged",flush=True)
    jobs=[]
    ssh=ftp=None
    try:
        ssh,ftp,root=_spr_direct_primary_sftp()
        original=_spr_direct_read(
            ftp,_np_os.environ["CPANEL_HOME"].rstrip("/")+
            "/sps-private-assets/rc230-proprietary-runtime.min.js",max_bytes=6_000_000)
        if b"EXD|DEX|OPD|EXG|GEX|SBTD|SBDT|SBTG|SBGT" not in original:
            raise RuntimeError("All nine shift prefixes not installed on the primary parser")
        version=_np_hashlib.sha256(original).hexdigest()
        for role,label in (("driver","Drivers"),("guard","Guards")):
            folder=_spr_remote_subdir(root,label.lower())
            pattern=_np_re.compile(
                r"^All "+label+r" Combined (\d{2})_(\d{2})_(20\d{2})\.pdf$")
            for filename in ftp.listdir(folder):
                match=pattern.fullmatch(filename)
                if not match:continue
                dd,mm,yyyy=match.groups()
                date=yyyy+"-"+mm+"-"+dd
                try:
                    if _np_datetime.date.fromisoformat(date).isoformat()!=date:continue
                except ValueError:continue
                path=folder+"/"+filename
                st=ftp.stat(path)
                if st.st_size<1000 or st.st_size>30_000_000:continue
                jobs.append((date,role,path,st.st_size))
        jobs.sort(key=lambda j:(j[0],j[1]),reverse=True)
        if not jobs or len(jobs)>150:
            raise RuntimeError("Unexpected date scope for all-source SPR reindex: "+str(len(jobs)))
        print("[SPR NINE PREFIX INVENTORY] dated_source_pairs="+str(len(jobs))+
              " primary_parser_sha="+version[:14],flush=True)
        resolved=[]
        for date,role,path,length in jobs:
            checkpoint=marker_dir/(date+"-"+role+"-"+version[:16]+".done")
            if checkpoint.is_file():
                resolved.append((date,role,None,checkpoint))
                continue
            cmd="sha256sum -- "+_np_shlex.quote(path)
            stdin,stdout,stderr=ssh.exec_command(cmd,timeout=20)
            stdout.channel.settimeout(45)
            line=stdout.read(240).decode("ascii","replace")
            rc=stdout.channel.recv_exit_status()
            stdin.close();stdout.close();stderr.close()
            if rc!=0 or not _np_re.match(r"^[a-f0-9]{64}  ",line):
                raise RuntimeError("Original PDF checksum command failed "+date+" "+role)
            resolved.append((date,role,line[:64],checkpoint))
        print("[SPR NINE PREFIX SOURCE HASHES] verified="+str(len(resolved)),flush=True)
    except Exception as exc:
        print("[SPR NINE PREFIX DISCOVERY_FAILED] "+type(exc).__name__+" "+
            str(exc)[:160],flush=True)
        return
    finally:
        if ftp is not None:
            try:ftp.close()
            except Exception:pass
        if ssh is not None:
            try:ssh.close()
            except Exception:pass
    complete=0
    skipped=0
    failed=0
    for date,role,sha,checkpoint in resolved:
        if sha is None:
            skipped+=1
            continue
        try:
            # The normal scheduled jobs retain priority between each source.
            if not _SPR_INDEX_RUNNING.acquire(timeout=180):
                raise RuntimeError("Index worker busy; defer backfill")
            try:
                _spr_direct_index_one({
                    "date":date,"role":role,"sha":sha,
                    "site":"https://www.bodgybros.com/sps"
                })
            finally:
                try:_dual_release_connection()
                except Exception:pass
                _SPR_INDEX_RUNNING.release()
            checkpoint.write_text(sha+"\n",encoding="ascii")
            complete+=1
            print("[SPR NINE PREFIX REINDEX_PASS] date="+date+" role="+role+
                  " completed="+str(complete)+" skipped="+str(skipped)+
                  " remaining="+str(len(resolved)-complete-skipped-failed),
                  flush=True)
        except Exception as exc:
            failed+=1
            print("[SPR NINE PREFIX REINDEX_REVIEW] date="+date+" role="+role+
                  " error="+type(exc).__name__+" "+str(exc)[:160],flush=True)
        _np_time.sleep(1.0)
    print("[SPR NINE PREFIX BACKFILL_SUMMARY] source_pairs="+str(len(resolved))+
          " reindexed_or_verified="+str(complete)+" previously_completed="+str(skipped)+
          " failed="+str(failed),flush=True)
    if failed==0:
        (marker_dir/"all-dates-complete.txt").write_text(
            "source_pairs="+str(len(resolved))+" parser_sha="+version+"\n",encoding="ascii")
        print("[SPR NINE PREFIX ALL_SOURCE_INDEXES_COMPLETE] count="+str(len(resolved)),
              flush=True)

if _np_os.environ.get("SPR_NINE_PREFIX_BACKFILL_ENABLED","1").strip()=="1":
    threading.Thread(target=_spr_nine_prefix_backfill,
                     name="spr-all-nine-prefix-backfill",daemon=True).start()
'''

def apply(path:Path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:
        print("[SPR NINE PREFIX] Already installed",flush=True);return
    tree=ast.parse(source)
    defined={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
    required={"_spr_direct_index_one","_spr_direct_primary_sftp","_spr_direct_read",
              "_spr_remote_subdir","_dual_release_connection"}
    if not required.issubset(defined):
        raise RuntimeError("Verified source indexer not present: "+str(sorted(required-defined)))
    if "_SPR_INDEX_RUNNING" not in source:
        raise RuntimeError("Original publisher lock absent")
    main=[n for n in tree.body if isinstance(n,ast.If) and
          "__name__" in (ast.get_source_segment(source,n.test) or "")]
    if not main:raise RuntimeError("Expected Railway updater entrypoint missing")
    insertion=main[-1].lineno-1
    lines=source.splitlines(keepends=True)
    updated="".join(lines[:insertion])+EXTENSION+"\n"+"".join(lines[insertion:])
    ast.parse(updated)
    compile(updated,str(path),"exec")
    path.write_text(updated,encoding="utf-8")
    print("[SPR NINE PREFIX PATCH READY] source-verified all-dates backfill using installed updater",flush=True)

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: patch.py updater.py")
    apply(Path(sys.argv[1]))
