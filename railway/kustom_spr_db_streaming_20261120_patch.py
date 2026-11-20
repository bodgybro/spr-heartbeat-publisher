#!/usr/bin/env python3
"""After both dated SPRs have been verified, import Kustom private SQLite.
This is a Kustom-only optional background extension; Bodgybros and original
SPR/roster update successes are independent of the database pilot.
"""
import ast
from pathlib import Path
import sys
MARKER="# KUSTOM_DATED_SPR_SQLITE_20261120_V1"
EXTENSION=r'''
# KUSTOM_DATED_SPR_SQLITE_20261120_V1
# Kustom host has PHP CLI and a private streaming importer; no Python3 needed there.
_SPR_DB_KUSTOM_PHP="/home10/kustomvi/sps-private-assets/spr-db-v1/spr-db-v1-import.php"
_SPR_DB_ORIGINAL_DATE_INDEXER=_spr_direct_index_one

def _spr_db_kustom_remote(args):
    import re as _dbre
    valid_commands=(("--jobs",),("--scan","3"))
    if tuple(args) not in valid_commands:
        if (len(args)!=3 or args[0]!="--one" or
            not _dbre.fullmatch(r"20\d\d-\d\d-\d\d",args[1]) or
            args[2] not in ("driver","guard")):
            raise ValueError("Invalid Kustom daily SPR import parameters")
    ssh=ftp=None
    try:
        ssh,ftp=_dual_kustom_open()
        command="/usr/local/bin/php -d max_execution_time=0 "+_SPR_DB_KUSTOM_PHP+" "+" ".join(args)
        stdin,stdout,stderr=ssh.exec_command(command,timeout=30)
        stdout.channel.settimeout(180)
        out=stdout.read(3500).decode("utf-8","replace")
        rc=stdout.channel.recv_exit_status()
        stdin.close();stdout.close();stderr.close()
        if rc:
            raise RuntimeError("Private importer returned "+str(rc))
        # Only aggregate status lines are passed back to Railway logs.
        rows=[l for l in out.splitlines() if l.startswith(
            ("SPR_DB_ONE ","SPR_DB_SCAN_SUMMARY ","SPR_DB_JOBS_DONE","SPR_DB_IMPORT_PASS "))]
        print("  [KUSTOM SPR DB] "+("; ".join(rows) if rows else "command completed")[:700],flush=True)
        return True
    finally:
        if ftp is not None:
            try:ftp.close()
            except Exception:pass
        if ssh is not None:
            try:ssh.close()
            except Exception:pass

def _spr_direct_index_one(job):
    # The original indexed PDF first must complete its existing dual-site
    # source-SHA/index publication. Failure stops here without DB work.
    result=_SPR_DB_ORIGINAL_DATE_INDEXER(job)
    if isinstance(job,dict) and job.get("date") and job.get("role"):
        try:_spr_db_kustom_remote(("--one",str(job["date"]),str(job["role"])))
        except Exception as exc:
            # Failure never damages original SPR download/indexing or Bodgybros.
            # The hourly private fallback will retry and import by hash later.
            print("  [KUSTOM SPR DB IMPORT DEFERRED] "+str(job.get("date"))+
                  " "+str(job.get("role"))+" "+type(exc).__name__,flush=True)
    return result

def _spr_db_kustom_scheduled_retry():
    from datetime import datetime as _dbdatetime
    from zoneinfo import ZoneInfo as _dbZoneInfo
    import time as _dbtime
    zone=_dbZoneInfo("Australia/Sydney")
    # No independent GitHub Actions or Kustom cron job.
    print("[KUSTOM SPR DB SCHEDULER READY] after verified SPR indexing; "
          "CLI jobs hourly and bounded source checks at 08/12/16/22",flush=True)
    previous=None
    while True:
        now=_dbdatetime.now(zone)
        if now.minute>=17 and (now.year,now.month,now.day,now.hour)!=previous:
            previous=(now.year,now.month,now.day,now.hour)
            try:_spr_db_kustom_remote(("--jobs",))
            except Exception as exc:
                print("  [KUSTOM SPR DB ADMIN QUEUE DEFERRED] "+type(exc).__name__,flush=True)
            if now.hour in (8,12,16,22):
                try:_spr_db_kustom_remote(("--scan","3"))
                except Exception as exc:
                    print("  [KUSTOM SPR DB SCAN DEFERRED] "+type(exc).__name__,flush=True)
        _dbtime.sleep(40)

threading.Thread(target=_spr_db_kustom_scheduled_retry,
                 daemon=True,name="kustom-spr-db-v1").start()
'''
def apply(path:Path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:
        print("[KUSTOM SPR DB] already configured",flush=True);return
    tree=ast.parse(source)
    names={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
    needed={"_spr_direct_index_one","_dual_kustom_open","_spr_index_background"}
    if not needed.issubset(names):
        raise RuntimeError("Existing verified Railway original-SPR pipeline absent; no changes made")
    mains=[n for n in tree.body if isinstance(n,ast.If) and
           "__name__" in (ast.get_source_segment(source,n.test) or "")]
    if len(mains)<1:raise RuntimeError("Safe Railway entrypoint missing")
    at=mains[-1].lineno-1
    lines=source.splitlines(keepends=True)
    updated="".join(lines[:at])+EXTENSION+"\n"+"".join(lines[at:])
    ast.parse(updated);compile(updated,str(path),"exec")
    path.write_text(updated,encoding="utf-8")
    print("[KUSTOM SPR DB PATCH READY] source-verified index -> private SQLite; no Bodgybros modification",flush=True)
if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("Usage: patch.py updater.py")
    apply(Path(sys.argv[1]))
