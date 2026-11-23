#!/usr/bin/env python3
"""Offline regression for immutable single-day ROC repair. No SharePoint access."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
from unittest.mock import patch
from datetime import date

ROOT=Path(__file__).resolve().parents[1]
PATCH=ROOT/"roc_backfill_20261119_patch.py"
spec=importlib.util.spec_from_file_location("roc19_patch",PATCH)
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

UPDATER='''# ROC_MANUAL_COMMAND_20261114_V1
import os
import threading
from pathlib import Path
DATA_ROOT=Path(".")
SHAREPOINT_BROWSE_LOCK=threading.Lock()
def load_config():return {"profile":"existing"}
def _launch_sharepoint_context(*args,**kwargs):return None
def _wait_for_sharepoint_profile_release():pass
def _roster_sftp_connection():pass
def _dual_kustom_open():pass
def online_control_worker():pass
def _roc_manual_check():pass
if __name__=="__main__":
    threading.Thread(target=online_control_worker,daemon=True).start()
'''

def execute(helper,root,mode):
    reports=[]
    released=[]
    browsers=[]
    sp=types.ModuleType('playwright')
    api=types.ModuleType('playwright.sync_api')
    class PW:
        def __enter__(self):return object()
        def __exit__(self,*a):return False
    api.sync_playwright=lambda:PW()
    sp.sync_api=api
    roc=types.ModuleType('roc_domo_daily_worker_20261104')
    def process(browser,env,target_date):
        assert target_date==date(2026,11,19),target_date
        assert "_roster_sftp_connection" in env and "_dual_kustom_open" in env
        reports.append(target_date)
        if mode=="failure":raise RuntimeError("ROC could not verify both sites")
        return True
    roc.process=process
    class Browser:
        def __init__(self):self.closed=False;browsers.append(self)
        def close(self):self.closed=True
    ns={"__name__":"fixture","__file__":"fixture.py"}
    exec(compile(helper,"test_updater.py","exec"),ns)
    ns.update({"DATA_ROOT":root,
        "_launch_sharepoint_context":lambda *a,**kw:Browser(),
        "_wait_for_sharepoint_profile_release":lambda:released.append(True)})
    capture=io.StringIO()
    with patch.dict(sys.modules,{"playwright":sp,"playwright.sync_api":api,
                                 "roc_domo_daily_worker_20261104":roc}):
        with patch("time.sleep",lambda seconds:None), contextlib.redirect_stdout(capture):
            ns["_roc_backfill_20261119_once"]()
    return capture.getvalue(),reports,released,browsers

def main():
    with tempfile.TemporaryDirectory() as tmp:
        f=Path(tmp)/"updater.py"
        f.write_text(UPDATER)
        patcher.apply(f)
        text=f.read_text()
        assert text.count("# ROC_MANUAL_COMMAND_20261114_V1")==1
        assert text.count("def _roc_manual_check():")==1
        assert text.count("if __name__==\"__main__\":")==1
        assert text.count("target=_roc_backfill_20261119_once")==1
        assert text.count("target=online_control_worker")==1
        compile(text,str(f),"exec")
        patcher.apply(f)
        assert text==f.read_text(),"Not idempotent"
        done=Path(tmp)/".roc-2026-11-19-backfill-complete"
        output,reports,released,browsers=execute(text,Path(tmp),"failure")
        assert "DEFERRED" in output and not done.exists()
        assert reports==[date(2026,11,19)] and len(released)==1
        assert len(browsers)==1 and browsers[0].closed
        output,reports,released,browsers=execute(text,Path(tmp),"success")
        assert "BACKFILL PASS" in output and done.exists()
        assert reports==[date(2026,11,19)] and len(released)==1
        assert len(browsers)==1 and browsers[0].closed
        output,reports,released,browsers=execute(text,Path(tmp),"success")
        assert "Already verified" in output and not reports and not browsers
        print("ROC_19NOV_BACKFILL_TEST_PASS target_exact=yes no_false_success=yes "
              "dual_site_validation=yes offline_safe=yes existing_scheduler_unchanged=yes")

if __name__=="__main__":
    main()
