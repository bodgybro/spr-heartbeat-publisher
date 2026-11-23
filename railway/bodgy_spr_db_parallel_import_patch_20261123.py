#!/usr/bin/env python3
"""Add Bodgybros independent daily SPR SQLite imports alongside Kustom imports.

Narrow additive patch for the existing Railway Kustom importer hooks. Both
sites retain their own private database; existing original-PDF index and
download results remain unaffected by optional database importer failures.
"""
import ast
from pathlib import Path
import sys

MARKER="# BODGY_INDEPENDENT_SPR_DB_IMPORT_20261123_V1"
EXTENSION=r'''
# BODGY_INDEPENDENT_SPR_DB_IMPORT_20261123_V1
# Retain the tested Kustom importer. Add an independent Bodgybros importer
# using the existing pinned/verified primary SFTP connection.
_SPR_DB_BODGY_IMPORT_PHP="/home11/bodgybro/sps-private-assets/spr-db-v1/spr-db-v1-import.php"
_SPR_DB_KUSTOM_IMPORT_ORIGINAL=_spr_db_kustom_remote

def _spr_db_bodgy_remote(args):
    import re
    opts=tuple(args)
    if opts not in (("--jobs",),("--scan","3")):
        if (len(opts)!=3 or opts[0]!="--one" or
            re.fullmatch(r"20\d\d-\d\d-\d\d",str(opts[1])) is None or
            opts[2] not in ("driver","guard")):
            raise ValueError("Invalid Bodgybros SPR database import operation")
    ssh=ftp=None
    try:
        ssh,ftp,_root=_spr_direct_primary_sftp()
        command="/usr/local/bin/php -d max_execution_time=0 "+_SPR_DB_BODGY_IMPORT_PHP+" "+" ".join(opts)
        stdin,stdout,stderr=ssh.exec_command(command,timeout=30)
        stdout.channel.settimeout(180)
        message=stdout.read(4000).decode("utf-8","replace")
        exit_code=stdout.channel.recv_exit_status()
        stdin.close()
        stdout.close()
        stderr.close()
        if exit_code!=0:
            raise RuntimeError("Independent Bodgybros SPR importer returned "+str(exit_code))
        allowed=("SPR_DB_ONE ","SPR_DB_SCAN_SUMMARY ","SPR_DB_JOBS_DONE","SPR_DB_IMPORT_PASS ")
        rows=[line for line in message.splitlines() if line.startswith(allowed)]
        print("  [BODGY SPR DB] "+("; ".join(rows) if rows else "command completed")[:700],flush=True)
        return True
    finally:
        if ftp is not None:
            try:ftp.close()
            except Exception:pass
        if ssh is not None:
            try:ssh.close()
            except Exception:pass

def _spr_db_kustom_remote(args):
    # Existing direct source verification and Kustom import must still run,
    # but a failure on one site should never block the other's import attempt.
    k_result=None
    k_error=None
    try:
        k_result=_SPR_DB_KUSTOM_IMPORT_ORIGINAL(args)
    except Exception as exc:
        k_error=exc
    try:
        _spr_db_bodgy_remote(args)
    except Exception as exc:
        label=" ".join(str(x) for x in args[:3])[:55]
        print("  [BODGY SPR DB DEFERRED] "+label+" "+type(exc).__name__,flush=True)
    if k_error is not None:
        raise k_error
    return k_result
'''

def apply(path:Path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:
        print("BODGY_SPR_DB_PARALLEL_IMPORT_ALREADY_INSTALLED")
        return
    tree=ast.parse(source)
    functions={node.name for node in tree.body if isinstance(node,ast.FunctionDef)}
    required={"_spr_db_kustom_remote","_spr_db_kustom_scheduled_retry",
              "_spr_direct_primary_sftp","_spr_direct_index_one"}
    if not required.issubset(functions):
        raise RuntimeError("Verified Kustom and original-PDF import hooks missing")
    if "# KUSTOM_DATED_SPR_SQLITE_20261120_V1" not in source:
        raise RuntimeError("Existing Kustom private SQLite importer not installed")
    mains=[node for node in tree.body if isinstance(node,ast.If)
           and "__name__" in (ast.get_source_segment(source,node.test) or "")]
    if len(mains)!=1:
        raise RuntimeError("Expected exactly one Railway updater entrypoint")
    i=mains[0].lineno-1
    lines=source.splitlines(keepends=True)
    patched="".join(lines[:i])+EXTENSION+"\n"+"".join(lines[i:])
    ast.parse(patched)
    compile(patched,str(path),"exec")
    path.write_text(patched,encoding="utf-8")
    print("BODGY_SPR_DB_PARALLEL_IMPORT_PATCH_PASS main_schedule_intact=yes Kustom_independent=yes")
if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: patch.py generated_railway_updater.py")
    apply(Path(sys.argv[1]))
