#!/usr/bin/env python3
"""Offline regression tests: never connect to Microsoft or mutate production."""
from pathlib import Path
import subprocess,sys,tempfile,importlib.util,types
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
PATCH=ROOT/"sharepoint_auto_catchup_patch_20261123.py"

FIXTURE = '''
# ROC_DOMO_NOON_ONLY_20261104_V2
# ROC_MANUAL_COMMAND_20261114_V1
# SPR_SCHEDULE_08_12_16_22_700
from pathlib import Path
from datetime import datetime
import time, threading, os
DATA_ROOT=Path('/tmp')
LOGIN_MARKER=DATA_ROOT/'signin-ok'
AUTO_RUN_TIMES=[(8,0),(12,0),(16,0),(22,0)]
JOB_LOCK=threading.Lock()
JOB={'running':False,'done':False}
def _online_control_endpoint():return 'https://example.invalid'
def _job_snapshot():return dict(JOB)
def scheduler_site_url():return 'https://site.example'
def start_background_update(site,mode='all',roc_noon=False):return True
def _record_online_success(kind):pass
def _sharepoint_session_ready(page):return False
def _set_online_progress(txt):pass
def _wait_for_sharepoint_signin(page, timeout_seconds=300):
    if _sharepoint_session_ready(page):
        return
    try:
        LOGIN_MARKER.unlink()
    except Exception:
        pass
    _set_online_progress("SharePoint sign-in required — open the online updater browser and complete Microsoft sign-in/MFA")
    deadline=time.time()+timeout_seconds
    while time.time()<deadline:
        if _sharepoint_session_ready(page):
            try:
                LOGIN_MARKER.write_text("SharePoint login confirmed\n",encoding="utf-8")
            except Exception:
                pass
            _set_online_progress("SharePoint sign-in restored — continuing update")
            return
        page.wait_for_timeout(1000)
    raise RuntimeError('sign-in required')
def _roc_manual_check():
    _record_online_success("roc")
    return [{'role':'ROC','message':'success'}]
def auto_update_scheduler():
    while True:
        try:
            now=datetime.now()
            for h,m in AUTO_RUN_TIMES:
                if start_background_update(scheduler_site_url(),roc_noon=(h==12 and m==0)):
                    pass
            _roc_date=now.date()
            _roc_marker=DATA_ROOT/(".roc-domo-noon-"+_roc_date.isoformat()+".ok")
        except Exception:pass
        time.sleep(20)
'''.replace('confirmed\n"', 'confirmed\\n"')
def main():
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'updater.py'
        path.write_text(FIXTURE)
        subprocess.run([sys.executable,str(PATCH),str(path)],check=True)
        subprocess.run([sys.executable,'-m','py_compile',str(path)],check=True)
        source=path.read_text()
        for marker in ['def _spr_recovery_tick():','_spr_recovery_auth_event(True)',
            '_spr_recovery_auth_event(False)','_spr_recovery_roc_success()']:
            assert marker in source,marker
        spec=importlib.util.spec_from_file_location('patched_updater',path)
        m=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        root=Path(tmp)
        m.DATA_ROOT=root
        m.LOGIN_MARKER=root/'signin-ok'
        m.LOGIN_MARKER.write_text('yes')
        now=datetime(2026,11,23,18,58,tzinfo=ZoneInfo('Australia/Sydney'))
        m._spr_recovery_clock=lambda:now
        due=int(datetime(2026,11,23,16,0,tzinfo=now.tzinfo).timestamp())
        state={'worker_online':True,'last_seen':int(now.timestamp()),
          'command_pending':False,'message':'Online updater ready','last_message':'SPR completed',
          'sprs_last_updated':due-1,'rosters_last_updated':due-1}
        class FakeResponse:
            def raise_for_status(self):pass
            def json(self):return dict(state)
        sys.modules['requests']=types.SimpleNamespace(get=lambda *args,**kwargs:FakeResponse())
        called=[]
        m.start_background_update=lambda site,mode='all',**opts:(called.append(mode),True)[-1]
        def tick():
            m._SPR_RECOVERY_LAST_CHECK=0
            m._spr_recovery_tick()
        tick()
        assert called==['spr'],called
        state['sprs_last_updated']=int(now.timestamp())
        tick()
        assert called==['spr','rosters'],called
        state['rosters_last_updated']=int(now.timestamp())
        tick()
        assert called==['spr','rosters','roc'],called
        m._spr_recovery_roc_success()
        tick()
        assert len(called)==3
        state['sprs_last_updated']=0
        (root/'.spr-catchup-attempt-spr').unlink()
        m._spr_recovery_auth_event(True)
        tick()
        assert len(called)==3
        m._spr_recovery_auth_event(False)
        state['command_pending']=True
        tick()
        assert len(called)==3
        state['command_pending']=False
        m.JOB['running']=True
        tick()
        assert len(called)==3
        m.JOB['running']=False
        tick()
        assert called==['spr','rosters','roc','spr'],called
        assert m._spr_recovery_date_target(now)=='2026-11-22'
        # A no-op subsequent application must not mutate a tested script.
        before=path.read_bytes()
        subprocess.run([sys.executable,str(PATCH),str(path)],check=True)
        assert path.read_bytes()==before
        print('CATCHUP_THREE_SOURCES_ALL_TESTS_PASS verified_success_only=yes missed_SPR=yes missed_roster=yes missed_ROC=yes skip_manual_busy=yes skip_expired_auth=yes skip_pending_command=yes no_duplicate=yes timezone=yes')
if __name__=='__main__':main()
