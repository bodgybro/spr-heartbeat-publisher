#!/usr/bin/env python3
"""Add independent Bodgybros daily SPR SQLite streaming to verified dual-site updater.

Runs after the Kustom database wrapper. Failures are non-fatal and retried
hourly, keeping the original SPR, roster, ROC paths working. No secrets in code.
"""
import ast
from pathlib import Path
import sys

MARKER="# BODGY_DATED_SPR_SQLITE_PARITY_20261123_V1"
EXTENSION=r'''
# BODGY_DATED_SPR_SQLITE_PARITY_20261123_V1
_SPR_DB_BODGY_PHP="/home11/bodgybro/sps-private-assets/spr-db-v1/spr-db-v1-import.php"
_SPR_DB_UPSTREAM_DATE_INDEXER=_spr_direct_index_one

def _spr_db_bodgy_remote(args):
    import re as _br
    valid=(("--jobs",),("--scan","3"),("--status",))
    if tuple(args) not in valid:
        if (len(args)!=3 or args[0]!="--one" or
            not _br.fullmatch(r"20\d\d-\d\d-\d\d",args[1]) or
            args[2] not in ("driver","guard")):
            raise ValueError("Invalid Bodgy daily SPR SQLite command")
    ssh=None;ftp=None
    try:
        # The existing primary helper verifies the server host key and
        # authenticates independently of Kustom. It does not alter files.
        ssh,ftp,_=_spr_direct_primary_sftp()
        command="/usr/local/bin/php -d max_execution_time=0 "+_SPR_DB_BODGY_PHP+" "+" ".join(args)
        stdin,stdout,stderr=ssh.exec_command(command,timeout=30)
        stdout.channel.settimeout(180)
        raw=stdout.read(3500).decode("utf-8","replace")
        rc=stdout.channel.recv_exit_status()
        stdin.close();stdout.close();stderr.close()
        if rc:
            raise RuntimeError("Bodgy private importer returned "+str(rc))
        lines=[line for line in raw.splitlines() if line.startswith(
            ("SPR_DB_ONE ","SPR_DB_SCAN_SUMMARY ","SPR_DB_JOBS_DONE",
             "SPR_DB_IMPORT_PASS ","SPR_DB_STATUS "))]
        print("  [BODGY SPR DB] "+("; ".join(lines) if lines else "command completed")[:700],flush=True)
        return True
    finally:
        if ftp is not None:
            try:ftp.close()
            except Exception:pass
        if ssh is not None:
            try:ssh.close()
            except Exception:pass

def _spr_direct_index_one(job):
    # First, original verified source index and Kustom import must finish.
    result=_SPR_DB_UPSTREAM_DATE_INDEXER(job)
    if isinstance(job,dict) and job.get("date") and job.get("role"):
        try:_spr_db_bodgy_remote(("--one",str(job["date"]),str(job["role"])))
        except Exception as exc:
            # The hourly private scan will retry by source SHA; never hold
            # back the live SPR update, its original index or Kustom pilot.
            print("  [BODGY SPR DB IMPORT DEFERRED] "+str(job.get("date"))+
                  " "+str(job.get("role"))+" "+type(exc).__name__,flush=True)
    return result

def _spr_db_bodgy_scheduled_retry():
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI
    import time as _clock
    zone=_ZI("Australia/Sydney")
    print("[BODGY SPR DB SCHEDULER READY] hourly jobs and 08/12/16/22 bounded scan",flush=True)
    previous=None
    while True:
        now=_dt.now(zone)
        key=(now.year,now.month,now.day,now.hour)
        if now.minute>=24 and key!=previous:
            previous=key
            try:_spr_db_bodgy_remote(("--jobs",))
            except Exception as exc:
                print("  [BODGY SPR DB ADMIN QUEUE DEFERRED] "+type(exc).__name__,flush=True)
            if now.hour in (8,12,16,22):
                try:_spr_db_bodgy_remote(("--scan","3"))
                except Exception as exc:
                    print("  [BODGY SPR DB SCAN DEFERRED] "+type(exc).__name__,flush=True)
        _clock.sleep(40)

threading.Thread(target=_spr_db_bodgy_scheduled_retry,
    daemon=True,name="bodgy-dated-spr-db").start()
'''
def apply(path:Path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:
        print("[BODGY SPR DB] parity patch already applied",flush=True)
        return
    tree=ast.parse(source)
    required={"_spr_direct_index_one","_spr_direct_primary_sftp",
              "_spr_db_kustom_remote","_spr_db_kustom_scheduled_retry"}
    names={n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    missing=required-names
    if missing:
        raise RuntimeError("Source lacks working Kustom/primary pipeline: "+str(sorted(missing)))
    if "# KUSTOM_DATED_SPR_SQLITE_20261120_V1" not in source:
        raise RuntimeError("Existing Kustom private SQLite pilot absent")
    main=[n for n in tree.body if isinstance(n,ast.If)
          and "__name__" in (ast.get_source_segment(source,n.test) or "")]
    if not main:raise RuntimeError("No safe active main block")
    rows=source.splitlines(keepends=True);pos=main[-1].lineno-1
    result="".join(rows[:pos])+EXTENSION+"\n"+"".join(rows[pos:])
    ast.parse(result);compile(result,str(path),"exec")
    if result.count(MARKER)!=1:
        raise RuntimeError("Private Bodgy import marker count invalid")
    tmp=path.with_suffix(path.suffix+".bodgy-db-staged")
    tmp.write_text(result,encoding="utf-8")
    tmp.replace(path)
    print("[BODGY SPR DB PARITY PREPARED] original verified index -> Kustom SQLite -> independent Bodgy SQLite",flush=True)

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("Usage: patch.py updater.py")
    apply(Path(sys.argv[1]))
