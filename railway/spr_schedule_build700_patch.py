#!/usr/bin/env python3
"""Build 700 recurring updater schedule, four Australia/Sydney slots.
Apply AFTER original schedule_idle_patch.py and all other updater patches;
never change PDF, roster files, source index, upload validation or credentials.
"""
import ast
import re
import sys
from pathlib import Path

MARKER="# SPR_SCHEDULE_08_12_16_22_700"
OLD_TIMES="AUTO_RUN_TIMES = [(10,0),(14,0),(20,0)]"
NEW_TIMES="AUTO_RUN_TIMES = [(8,0),(12,0),(16,0),(22,0)]"
OLD_NOTE="Automatic SPR + roster updates: 10:00, 14:00, 20:00 Australia/Sydney."
NEW_NOTE="Automatic SPR + roster updates: 08:00, 12:00, 16:00, 22:00 Australia/Sydney."
OLD_STATUS='["10:00","14:00","20:00"]'
NEW_STATUS='["08:00","12:00","16:00","22:00"]'

def patch_fn(source,name,old,new):
    tree=ast.parse(source)
    matches=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
    if len(matches)!=1:raise RuntimeError("Expected one updater function "+name)
    node=matches[0]
    lines=source.splitlines(keepends=True)
    body="".join(lines[node.lineno-1:node.end_lineno])
    if body.count(old)!=1:
        raise RuntimeError("Unexpected "+name+" schedule source; no file written")
    body=body.replace(old,new,1)
    return "".join(lines[:node.lineno-1])+body+"".join(lines[node.end_lineno:])

def apply(path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:
        print("[BUILD 700 SCHEDULE] Already installed",flush=True)
        return
    if source.count(OLD_TIMES)!=1:
        raise RuntimeError("Current AUTO_RUN_TIMES is not 10/14/20")
    updated=source.replace(OLD_TIMES,NEW_TIMES,1)
    updated=patch_fn(updated,"auto_update_scheduler",OLD_NOTE,NEW_NOTE)
    updated=patch_fn(updated,"publish_updater_status",OLD_STATUS,NEW_STATUS)
    if (updated.count(NEW_TIMES)!=1 or NEW_NOTE not in updated or NEW_STATUS not in updated):
        raise RuntimeError("Build 700 schedule validation failed")
    updated=MARKER+"\n"+updated
    compile(updated,str(path),"exec")
    path.write_text(updated,encoding="utf-8")
    print("[BUILD 700 SCHEDULE READY] 08:00, 12:00, 16:00, 22:00 Australia/Sydney; same SPR and roster updater",flush=True)

if __name__=="__main__":apply(Path(sys.argv[1]))
