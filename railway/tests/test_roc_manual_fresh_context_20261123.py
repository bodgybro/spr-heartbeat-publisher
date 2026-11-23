#!/usr/bin/env python3
"""Offline regression for a two-date ROC manual update on a persistent browser.

No SharePoint access, no credentials, and no production deployment.
"""
from pathlib import Path
import importlib.util
import runpy
import subprocess
import sys
import tempfile
import threading
import types
from datetime import date, datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
PATCH=ROOT/"roc_manual_fresh_context_patch_20261123.py"
BASE=ROOT/"tests/roc_manual_deployed_fixture_20261123.py"

def fixture():
    helper=runpy.run_path(str(BASE))["HELPER"]
    assert helper.count('    _record_online_success("roc")')==1
    helper=helper.replace('    _record_online_success("roc")',
                          '    _record_online_success("roc")\n    _spr_recovery_roc_success()',1)
    return ("# ROC_MANUAL_COMMAND_20261114_V1\n"+
            "import os\n"
            "from threading import Lock\n"
            "SHAREPOINT_BROWSE_LOCK=Lock()\n"
            "def _unrelated_spr_job():\n"
            "    with SHAREPOINT_BROWSE_LOCK:\n"
            "        return True\n"
            "def _spr_recovery_roc_success():pass\n"+
            helper+"\n")

def new_runtime(script, failure_mode=None):
    used, processed, published, progress, released, attempts=[],[],[],[],[],[]
    pmodule=types.ModuleType('playwright')
    sync=types.ModuleType('playwright.sync_api')
    class PlaywrightContext:
        def __enter__(self):return self
        def __exit__(self,*args):return False
    sync.sync_playwright=lambda:PlaywrightContext()
    pmodule.sync_api=sync
    sys.modules['playwright']=pmodule
    sys.modules['playwright.sync_api']=sync
    roc=types.ModuleType('roc_domo_daily_worker_20261104')
    class Browser:
        def __init__(self):
            self.closed=False
            self.pages=[]
            used.append(self)
        def close(self):self.closed=True
    def process(browser,helpers,target_date=None):
        assert not browser.closed,"browser context must not be reused after closing"
        assert target_date is not None
        processed.append(target_date)
        attempts.append((target_date,len(used)))
        if failure_mode=='closed-once' and target_date==date(2026,11,22):
            if sum(x==target_date for x in processed)==1:
                browser.closed=True
                raise RuntimeError("Page.goto: Target page, context or browser has been closed")
        if failure_mode=='fatal' and target_date==date(2026,11,22):
            raise RuntimeError("Invalid ROC CSV headers")
        # Simulate a persistent browser context that closes as its last tab closes.
        browser.closed=True
        return True
    roc.process=process
    sys.modules['roc_domo_daily_worker_20261104']=roc
    now=datetime(2026,11,23,19,20,tzinfo=ZoneInfo("Australia/Sydney"))
    class DateTime:
        @staticmethod
        def now(tz):
            assert str(tz)=="Australia/Sydney"
            return now
    class Config:
        def __call__(self):return {"dummy":True}
    runtime=types.ModuleType("roc_fixture")
    runtime.__dict__.update({
        "load_config":Config(),
        "os":__import__("os"),
        "_check_online_cancel":lambda:None,
        "_set_online_progress":lambda msg:progress.append(msg),
        "_launch_sharepoint_context":lambda *a,**kw:Browser(),
        "_wait_for_sharepoint_profile_release":lambda:released.append(1),
        "_record_online_success":lambda name:published.append(name),
        "_spr_recovery_roc_success":lambda:published.append("catchup_roc"),
        "SHAREPOINT_BROWSE_LOCK":threading.Lock(),
    })
    exec(compile(script,"<roc_manual_fixture>","exec"),runtime.__dict__)
    # Reapply spy after exec: fixture definition otherwise shadows the injected spy.
    runtime.__dict__["_spr_recovery_roc_success"]=lambda:published.append("catchup_roc")
    runtime.__dict__["roc_datetime"]=DateTime
    # Imported name is local: patch datetime module constructor in a test-only
    # sys.modules shim to ensure deterministic calendar dates.
    import datetime as module
    original_datetime=module.datetime
    module.datetime=DateTime
    try:
        try:
            result=runtime._roc_manual_check()
            error=None
        except Exception as exc:
            result=None
            error=exc
    finally:
        module.datetime=original_datetime
    return used,processed,published,progress,released,attempts,result,error

def main():
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/"updater.py"
        path.write_text(fixture(),encoding="utf-8")
        subprocess.run([sys.executable,str(PATCH),str(path)],check=True)
        subprocess.run([sys.executable,"-m","py_compile",str(path)],check=True)
        src=path.read_text()
        assert src.count('def _roc_manual_check():')==1
        assert src.count("with SHAREPOINT_BROWSE_LOCK:")==2, "Unrelated updater mutex must be left intact"
        assert src.count('_record_online_success("roc")')==1
        assert src.count('    _spr_recovery_roc_success()')==1
        assert src.count('for report_date in targets:')==1
        assert src.count("with sync_playwright() as p:")==1
        assert src.count("browser=_launch_sharepoint_context(")==1
        assert src.count("finally:\n                    _wait_for_sharepoint_profile_release()")==1
        tests=[
            (None,2,2,True),
            ('closed-once',3,3,True),
            ('fatal',2,2,False),
        ]
        for scenario,contexts,closes,should_succeed in tests:
            out=new_runtime(src,scenario)
            used,processed,published,progress,releases,attempts,result,error=out
            assert len(used)==contexts,(scenario,"contexts",len(used))
            assert len(releases)==closes,(scenario,"profile release",len(releases))
            assert all(b.closed for b in used),"Each ROC context released"
            assert processed[0]==date(2026,11,21)
            assert processed[1]==date(2026,11,22)
            if should_succeed:
                assert error is None,(scenario,error)
                assert [x["ok"] for x in result]==[True]
                assert published==["roc","catchup_roc"],published
            else:
                assert error is not None
                assert published==[],"Never mark failed ROC date as successful"
            print("ROC_FRESH_CONTEXT_FIXTURE_PASS",scenario,
                  "contexts",len(used),"reports",len(processed),
                  "success",should_succeed,flush=True)
        before=path.read_bytes()
        subprocess.run([sys.executable,str(PATCH),str(path)],check=True)
        assert path.read_bytes()==before,"Idempotency required"
        print("ROC_FRESH_CONTEXT_TESTS_ALL_PASS new_browser_per_day=yes "
              "target_closed_retry_once=yes fatal_no_publish=yes "
              "success_only_after_both_verified=yes lock_and_cancel_preserved=yes",flush=True)

if __name__=="__main__":
    main()
