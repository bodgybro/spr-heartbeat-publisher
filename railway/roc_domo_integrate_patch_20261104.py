#!/usr/bin/env python3
"""Fail-safe ROC DOMO integration with existing signed-in SharePoint browser.
Adds a bounded ROC step during roster updates and one startup catch-up check.
If ROC is unavailable, the existing SPR and roster update is not affected.
"""
import ast
from pathlib import Path
import sys

MARKER = "# ROC_DOMO_SHAREPOINT_20261104_V1"
def apply(path):
    src = path.read_text(encoding="utf-8")
    if MARKER in src:
        print("[ROC DOMO PATCH] Already installed",flush=True)
        return
    if "def _launch_sharepoint_context(" not in src or "SHAREPOINT_BROWSE_LOCK" not in src:
        raise RuntimeError("Current authenticated SharePoint browser hooks missing")
    if "def _roster_sftp_connection(" not in src or "def _dual_kustom_open(" not in src:
        raise RuntimeError("Verified primary/secondary private SFTP hooks missing")
    needle = "            depots=_sharepoint_depot_pages(page,root)"
    if src.count(needle)!=1:
        raise RuntimeError("Current roster browser launch/source structure changed; ROC not installed")
    inserted = """            # ROC DOMO extraction shares the authenticated browser session
            # without navigating or changing the existing TCREW roster tab.
            try:
                import roc_domo_daily_worker_20261104 as _roc_domo_worker
                _roc_domo_worker.safe_process(browser,globals())
            except Exception as _roc_domo_exception:
                print("[ROC DOMO] Skipped within roster update: "+
                      type(_roc_domo_exception).__name__,flush=True)
"""
    src=src.replace(needle,inserted+needle,1)
    before_main = """
def _roc_domo_startup_catchup():
    # Initial check is independent of the SPR/roster schedule. Only the same
    # persistent authenticated Chrome profile and existing browser lock are used.
    try:
        import time as _roc_time
        from datetime import datetime as _roc_dt, timedelta as _roc_td
        from zoneinfo import ZoneInfo as _roc_ZoneInfo
        import roc_domo_daily_worker_20261104 as _roc_domo_worker
        _roc_time.sleep(70)
        yesterday=_roc_dt.now(_roc_ZoneInfo("Australia/Sydney")).date()-_roc_td(days=1)
        marker=DATA_ROOT/(".roc-domo-initial-"+yesterday.isoformat()+".ok")
        if marker.exists():
            return
        from playwright.sync_api import sync_playwright as _roc_playwright
        cfg=load_config()
        with SHAREPOINT_BROWSE_LOCK:
            with _roc_playwright() as p:
                browser=_launch_sharepoint_context(
                    p,cfg,
                    headless=str(os.environ.get("SPR_HEADLESS","0")).strip().lower() in
                             ("1","true","yes","on"),
                    ignore_https_errors=True,accept_downloads=True,
                    args=["--window-size=900,650","--window-position=20,20"],
                    no_viewport=True)
                try:
                    if _roc_domo_worker.safe_process(browser,globals()):
                        marker.write_text("success",encoding="utf-8")
                finally:
                    browser.close()
        _wait_for_sharepoint_profile_release()
    except Exception as exc:
        print("[ROC DOMO] Startup catch-up skipped: "+type(exc).__name__+
              ": "+str(exc)[:130],flush=True)

"""
    main='if __name__=="__main__":'
    if src.count(main)!=1:
        raise RuntimeError("Updater main entrypoint not found uniquely")
    src=src.replace(main,before_main+main,1)
    start="    threading.Thread(target=auto_update_scheduler,daemon=True).start()"
    if src.count(start)!=1:
        raise RuntimeError("Scheduler startpoint changed; ROC patch not installed")
    src=src.replace(start,
        start+"\n    threading.Thread(target=_roc_domo_startup_catchup,"
              "daemon=True,name='roc-domo-catchup').start()",1)
    src=MARKER+"\n"+src
    ast.parse(src)
    compile(src,str(path),"exec")
    path.write_text(src,encoding="utf-8")
    print("[ROC DOMO PATCH READY] Same SharePoint session, 8/12/16/22 sync, "
          "private two-site CSV storage; SPR/roster behavior preserved",flush=True)

if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("Usage: patch.py /app/spr_online_updater.py")
    apply(Path(sys.argv[1]))
