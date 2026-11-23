#!/usr/bin/env python3
"""One-shot recovery of the missing 19 Nov 2026 ROC report.

Run after the verified dual-site ROC worker patches, before updater start.
Uses the existing persistent authenticated SharePoint profile and publishes
via the existing private, SHA-verified two-site ROC CSV importer. Does NOT
change ongoing update schedules, other ROC dates, the reader, or SPR/rosters.
"""
import ast
import os
import sys
from pathlib import Path

MARKER="# ROC_BACKFILL_20261119_PRIVATE_DUAL_SITE_V1"

HELPER=r'''
# ROC_BACKFILL_20261119_PRIVATE_DUAL_SITE_V1
# File content and personal details are NEVER sent to logs or source control.
def _roc_backfill_20261119_once():
    import time as _rbtime
    from datetime import date as _rbdate
    from playwright.sync_api import sync_playwright as _rb_sync_playwright
    import roc_domo_daily_worker_20261104 as _rb_worker
    completed=DATA_ROOT/'.roc-2026-11-19-backfill-complete'
    if completed.exists():
        print('[ROC 19 NOV BACKFILL] Already verified on both sites',flush=True)
        return
    # Allow normal updater launch, display server and persistent profile to settle.
    _rbtime.sleep(35)
    browser=None
    try:
        with SHAREPOINT_BROWSE_LOCK:
            try:
                cfg=load_config()
                with _rb_sync_playwright() as p:
                    browser=_launch_sharepoint_context(
                        p,cfg,
                        headless=str(os.environ.get('SPR_HEADLESS','0')).strip().lower()
                        in ('1','true','yes','on'),
                        ignore_https_errors=True,accept_downloads=True,
                        args=['--window-size=900,650','--window-position=20,20'],
                        no_viewport=True)
                    try:
                        # The worker validates nine CSV fields and SHA-256 on
                        # both private hosting directories before returning True.
                        if not _rb_worker.process(
                            browser,globals(),target_date=_rbdate(2026,11,19)):
                            raise RuntimeError('ROC worker did not verify both sites')
                    finally:
                        try:browser.close()
                        except Exception:pass
                        browser=None
            finally:
                _wait_for_sharepoint_profile_release()
        completed.write_text(
            'date=2026-11-19\\nresult=private_dual_site_verified\\n',
            encoding='ascii')
        print('[ROC 19 NOV BACKFILL PASS] 2026-11-19 private CSV verified on both sites',flush=True)
    except Exception as exc:
        # No incident rows, filenames, URLs, cookies or session secrets logged.
        print('[ROC 19 NOV BACKFILL DEFERRED] '+type(exc).__name__,flush=True)
'''

def apply(path):
    path=Path(path)
    source=path.read_text(encoding="utf-8")
    if MARKER in source:
        print("ROC_19NOV_BACKFILL_ALREADY_INSTALLED",flush=True)
        return
    required=(
        "# ROC_MANUAL_COMMAND_20261114_V1",
        "SHAREPOINT_BROWSE_LOCK",
        "def _launch_sharepoint_context(",
        "def _wait_for_sharepoint_profile_release(",
        "def _roster_sftp_connection(",
        "def _dual_kustom_open(",
    )
    if any(x not in source for x in required):
        raise RuntimeError("Verified ROC/browser/dual-host pipeline unavailable; no changes made")
    main='if __name__=="__main__":'
    starter='    threading.Thread(target=online_control_worker,daemon=True).start()'
    if source.count(main)!=1 or source.count(starter)!=1:
        raise RuntimeError("Updater startup changed; refusing to add backfill")
    tree=ast.parse(source)
    funcs={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
    if not {"load_config","_launch_sharepoint_context",
            "_wait_for_sharepoint_profile_release"}.issubset(funcs):
        raise RuntimeError("ROC authenticated browser helpers not available")
    # Helpers are inserted after all existing functions but before the main
    # entrypoint, and a daemon starts independently after normal control poll.
    updated=source.replace(main,HELPER+"\n"+main,1)
    updated=updated.replace(
        starter,starter+
        "\n    threading.Thread(target=_roc_backfill_20261119_once,"
        "daemon=True,name='roc-19nov-one-shot').start()",1)
    ast.parse(updated)
    compile(updated,str(path),"exec")
    temp=path.with_name(path.name+".roc19-new")
    temp.write_text(updated,encoding="utf-8")
    os.replace(temp,path)
    print("ROC_19NOV_BACKFILL_PATCH_PASS isolated_date=yes dual_private_SHA=yes schedules_unchanged=yes",flush=True)

if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("usage: roc_19nov_backfill_patch.py /app/spr_online_updater.py")
    apply(sys.argv[1])
