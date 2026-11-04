#!/usr/bin/env python3
"""Run ROC CSV updates ONLY during the 12:00 Australia/Sydney scheduled update.

V1 integrates ROC with every roster run and starts a separate catch-up after
startup. This V2 patch removes both sources of additional checks and passes
an explicit noon-only flag into the existing scheduler's worker thread.

SPR/roster scheduled updates at 08:00, 12:00, 16:00, 22:00 are unchanged.
"""
import ast
import sys
from pathlib import Path

MARKER="# ROC_DOMO_NOON_ONLY_20261104_V2"
OLD_MARKER="# ROC_DOMO_SHAREPOINT_20261104_V1"

OLD_HOOK='''            # ROC DOMO extraction shares the authenticated browser session
            # without navigating or changing the existing TCREW roster tab.
            try:
                import roc_domo_daily_worker_20261104 as _roc_domo_worker
                _roc_domo_worker.safe_process(browser,globals())
            except Exception as _roc_domo_exception:
                print("[ROC DOMO] Skipped within roster update: "+
                      type(_roc_domo_exception).__name__,flush=True)
'''

NEW_HOOK='''            # Run ROC only for this thread's 12:00 Sydney scheduled update.
            # Manual, startup and the other three daily update slots never check.
            if getattr(_roc_domo_noon_thread, "enabled", False):
                try:
                    from datetime import datetime as _roc_datetime, timedelta as _roc_timedelta
                    from zoneinfo import ZoneInfo as _roc_timezone
                    import roc_domo_daily_worker_20261104 as _roc_domo_worker
                    _roc_date=(_roc_datetime.now(_roc_timezone("Australia/Sydney"))
                               -_roc_timedelta(days=1)).date()
                    _roc_marker=DATA_ROOT/(".roc-domo-noon-"+_roc_date.isoformat()+".ok")
                    if _roc_marker.is_file():
                        print("[ROC DOMO] Noon report already verified today; no repeat check",flush=True)
                    elif _roc_domo_worker.safe_process(browser,globals()):
                        _roc_marker.write_text("success",encoding="utf-8")
                except Exception as _roc_domo_exception:
                    print("[ROC DOMO] Noon check failed: "+
                          type(_roc_domo_exception).__name__,flush=True)
'''

STARTUP_CALL='''    threading.Thread(target=_roc_domo_startup_catchup,daemon=True,name='roc-domo-catchup').start()'''
EXACT_START='''def start_background_update(site, mode="all"):'''
CHANGED_START='''def start_background_update(site, mode="all", roc_noon=False):'''

def function_part(src,name):
    tree=ast.parse(src)
    hits=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    if len(hits)!=1:
        raise RuntimeError("Unexpected updater function "+name+": "+str(len(hits)))
    lines=src.splitlines(keepends=True)
    n=hits[0]
    return lines,n,"".join(lines[n.lineno-1:n.end_lineno])

def edit_function(src,name,old,new):
    lines,node,body=function_part(src,name)
    if body.count(old)!=1:
        raise RuntimeError("Unexpected "+name+" fragment (found "+str(body.count(old))+")")
    changed=body.replace(old,new,1)
    return "".join(lines[:node.lineno-1])+changed+"".join(lines[node.end_lineno:])

def apply(path):
    src=path.read_text(encoding="utf-8")
    if MARKER in src:
        print("[ROC DOMO NOON] Already applied",flush=True)
        return
    if src.count(OLD_MARKER)!=1:
        raise RuntimeError("V1 ROC SharePoint integration is not uniquely present")
    if src.count(OLD_HOOK)!=1:
        raise RuntimeError("Expected old every-roster ROC hook not found")
    if src.count(STARTUP_CALL)!=1:
        raise RuntimeError("Expected ROC startup catch-up call not found")
    if src.count(EXACT_START)!=1:
        raise RuntimeError("Expected background updater signature not found")
    src=src.replace(OLD_HOOK,NEW_HOOK,1)
    # Remove the independent startup checker and launch (including its 70s delay).
    lines,node,body=function_part(src,"_roc_domo_startup_catchup")
    src="".join(lines[:node.lineno-1])+"".join(lines[node.end_lineno:])
    src=src.replace(STARTUP_CALL,"",1)
    # Explicitly associate this scheduled update with its worker thread;
    # a wall-clock comparison during the roster stage would be inaccurate.
    anchor=EXACT_START
    src=src.replace(anchor,"_roc_domo_noon_thread=threading.local()\n\n"+CHANGED_START,1)
    src=edit_function(src,"start_background_update",
                      '    def worker():\n        try:',
                      '    def worker():\n'
                      '        _roc_domo_noon_thread.enabled = bool(roc_noon)\n'
                      '        try:')
    src=edit_function(src,"auto_update_scheduler",
                      'start_background_update(site)',
                      'start_background_update(site, roc_noon=(h==12 and m==0))')
    if ("_roc_domo_startup_catchup" in src or "safe_process(browser,globals())" not in src
        or "roc_noon=(h==12 and m==0)" not in src):
        raise RuntimeError("ROC noon-only assertions failed")
    src=MARKER+"\n"+src
    ast.parse(src)
    compile(src,str(path),"exec")
    path.write_text(src,encoding="utf-8")
    print("[ROC DOMO NOON ONLY] ROC download at 12:00 Sydney scheduled update; "
          "no startup/manual/08:00/16:00/22:00 ROC checks; "
          "SPR and roster schedule unchanged",flush=True)

if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("Usage: python roc_domo_noon_only_20261104.py /app/spr_online_updater.py")
    apply(Path(sys.argv[1]))
