#!/usr/bin/env python3
"""Install safe automatic SPR, roster and ROC catch-up after SharePoint recovery.

Applies AFTER all current Railway patches (including the manual ROC patch).
Changes neither the existing schedule times nor download/validation logic.
"""
import ast
from pathlib import Path
import sys

MARKER = "# SHAREPOINT_AUTO_CATCHUP_THREE_SOURCES_20261123_V1"

HELPERS = r'''
# SHAREPOINT_AUTO_CATCHUP_THREE_SOURCES_20261123_V1
# An unattended authentication expiry can lose a scheduled slot because the
# original scheduler records every attempted slot. This worker repairs misses
# using Cloudflare's *verified success* timestamps, never attempted slots.
_SPR_RECOVERY_LAST_CHECK = 0.0
_SPR_RECOVERY_ATTEMPT_BACKOFF = 30 * 60

def _spr_recovery_clock():
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _zone
    return _dt.now(_zone("Australia/Sydney"))

def _spr_recovery_path(name):
    import re as _re
    if not _re.fullmatch(r"[a-z0-9._-]{1,100}", name):
        raise ValueError("Unexpected catch-up marker name")
    return DATA_ROOT / name

def _spr_recovery_date_target(now):
    from datetime import timedelta as _td
    # Noon ROC check imports the preceding day's incident CSV.
    return (now.date() - _td(days=1 if now.hour >= 12 else 2)).isoformat()

def _spr_recovery_roc_success():
    target = _spr_recovery_date_target(_spr_recovery_clock())
    _spr_recovery_path(".spr-catchup-roc-" + target + ".ok").write_text("verified\n",encoding="utf-8")
    print("[SPR CATCHUP] ROC source date " + target + " verified",flush=True)

def _spr_recovery_auth_event(required):
    # A warning persists through server restarts. Re-sign-in resets it; the
    # scheduled monitor then knows it can retry pending work.
    path=_spr_recovery_path(".spr-sharepoint-auth-needed")
    try:
        if required:
            if not path.exists():
                path.write_text("required\n",encoding="utf-8")
                print("[SPR CATCHUP] Waiting for SharePoint sign-in",flush=True)
        else:
            path.unlink(missing_ok=True)
            print("[SPR CATCHUP] SharePoint session restored; checking missed jobs",flush=True)
    except Exception as exc:
        print("[SPR CATCHUP] Authentication state marker unavailable: "+type(exc).__name__,flush=True)

def _spr_recovery_latest_slot(now):
    from datetime import datetime as _dt, timedelta as _td, time as _time
    slots=((8,0),(12,0),(16,0),(22,0))
    today=now.date()
    ordered=[_dt.combine(today,_time(h,m),tzinfo=now.tzinfo) for h,m in slots]
    earlier=[dt for dt in ordered if dt<=now]
    return max(earlier) if earlier else _dt.combine(today-_td(days=1),_time(22,0),tzinfo=now.tzinfo)

def _spr_recovery_status():
    # Read nonsecret, user-facing Cloudflare status. Verify heartbeat recency
    # and never start if another Admin or scheduled command is pending.
    import requests as _requests
    value=_requests.get(_online_control_endpoint()+"/updater-status.json",timeout=(3,8))
    value.raise_for_status()
    data=value.json()
    if not isinstance(data,dict) or not data.get("worker_online") or data.get("command_pending"):
        return None
    age=int(_spr_recovery_clock().timestamp())-int(data.get("last_seen") or 0)
    if not -30<=age<=600:return None
    return data

def _spr_recovery_tick():
    global _SPR_RECOVERY_LAST_CHECK
    import time as _time
    now_mono=_time.monotonic()
    if now_mono-_SPR_RECOVERY_LAST_CHECK<90:return
    _SPR_RECOVERY_LAST_CHECK=now_mono
    try:
        if _job_snapshot().get("running"):
            return
        if _spr_recovery_path(".spr-sharepoint-auth-needed").exists():
            return
        if not LOGIN_MARKER.exists():
            return
        status=_spr_recovery_status()
        if not status:return
        state=str(status.get("message") or "")+" "+str(status.get("last_message") or "")
        if "SHAREPOINT SIGN-IN REQUIRED" in state.upper() and "SIGN-IN DETECTED" not in state.upper():
            return
        now=_spr_recovery_clock()
        latest=_spr_recovery_latest_slot(now)
        must_have=int(latest.timestamp())
        tasks=[]
        if int(status.get("sprs_last_updated") or 0)<must_have:
            tasks.append("spr")
        if int(status.get("rosters_last_updated") or 0)<must_have:
            tasks.append("rosters")
        date=_spr_recovery_date_target(now)
        noon=_spr_recovery_path(".roc-domo-noon-"+date+".ok")
        manual=_spr_recovery_path(".spr-catchup-roc-"+date+".ok")
        if not noon.exists() and not manual.exists():
            tasks.append("roc")
        if not tasks:return
        target=tasks[0]
        due=(date if target=="roc" else str(must_have))
        # Persist attempt-time backoff to avoid repeated SharePoint prompts
        # after transient errors, and preserve this across process restarts.
        marker=_spr_recovery_path(".spr-catchup-attempt-"+target)
        if marker.exists() and _time.time()-marker.stat().st_mtime<_SPR_RECOVERY_ATTEMPT_BACKOFF:
            return
        site=scheduler_site_url()
        if not site:return
        if _job_snapshot().get("running"):
            return
        # The existing start_background_update() owns the same JOB_LOCK and
        # Chromium browsing lock as manual/scheduled work. Never run in parallel.
        if start_background_update(site,mode=target):
            marker.write_text(due+"\n",encoding="utf-8")
            print("[SPR CATCHUP] Started missed "+target+" update; due="+due,flush=True)
    except Exception as exc:
        print("[SPR CATCHUP] Deferred: "+type(exc).__name__+": "+str(exc)[:130],flush=True)
'''

def replace_func(source, name, transform):
    tree=ast.parse(source)
    matches=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
    if len(matches)!=1:
        raise RuntimeError(f"Expected one {name} function, found {len(matches)}")
    node=matches[0]
    lines=source.splitlines(keepends=True)
    old="".join(lines[node.lineno-1:node.end_lineno])
    new=transform(old)
    if old==new:raise RuntimeError(f"No change to {name}")
    return "".join(lines[:node.lineno-1])+new.rstrip()+"\n"+"".join(lines[node.end_lineno:])

def change_exact(block, before, after, label):
    count=block.count(before)
    if count!=1:
        raise RuntimeError(f"{label}: found {count} matching anchors")
    return block.replace(before,after,1)

def patch(path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:
        print("[SPR CATCHUP] Already installed",flush=True)
        return
    for required in (
        "# ROC_DOMO_NOON_ONLY_20261104_V2",
        "# ROC_MANUAL_COMMAND_20261114_V1",
        "# SPR_SCHEDULE_08_12_16_22_700",
        "def _record_online_success(",
        "def _wait_for_sharepoint_signin(",
        "def start_background_update(",
        "def auto_update_scheduler(",
        "def _roc_manual_check(",
    ):
        if source.count(required)!=1:raise RuntimeError(f"Missing verified deployed hook {required}")
    source=change_exact(source,"def auto_update_scheduler():",HELPERS+"\ndef auto_update_scheduler():","Add catchup helpers")
    def schedule(block):
        return change_exact(block,"        time.sleep(20)",
            "        _spr_recovery_tick()\n        time.sleep(20)",
            "Run catchup only between normal scheduled intervals")
    source=replace_func(source,"auto_update_scheduler",schedule)
    def sign_in(block):
        block=change_exact(block,
            '    _set_online_progress("SharePoint sign-in required — open the online updater browser and complete Microsoft sign-in/MFA")',
            '    _spr_recovery_auth_event(True)\n    _set_online_progress("SharePoint sign-in required — open the online updater browser and complete Microsoft sign-in/MFA")',
            "Set recovery pending on expired SharePoint session")
        block=change_exact(block,
            '            _set_online_progress("SharePoint sign-in restored — continuing update")',
            '            _spr_recovery_auth_event(False)\n            _set_online_progress("SharePoint sign-in restored — continuing update")',
            "Rearm missed tasks on Microsoft sign-in recovery")
        block=change_exact(block,
            '    if _sharepoint_session_ready(page):\n        return',
            '    if _sharepoint_session_ready(page):\n        _spr_recovery_auth_event(False)\n        return',
            "Clear prior expired-session marker when current session is ready")
        return block
    source=replace_func(source,"_wait_for_sharepoint_signin",sign_in)
    def manual_roc(block):
        return change_exact(block,
            '    _record_online_success("roc")',
            '    _record_online_success("roc")\n    _spr_recovery_roc_success()',
            'Track verified manual ROC report date')
    source=replace_func(source,"_roc_manual_check",manual_roc)
    assert source.count('".roc-domo-noon-"+_roc_date.isoformat()+".ok"')==1
    assert source.count(MARKER)==1
    assert source.count("def _spr_recovery_tick():")==1
    assert source.count("def auto_update_scheduler():")==1
    assert source.count("        _spr_recovery_tick()") == 1
    ast.parse(source)
    compile(source,str(path),"exec")
    path.write_text(source,encoding="utf-8")
    print("[SPR CATCHUP] Installed validated, no-overlap recovery for SPRs, rosters and ROC; normal schedule unchanged",flush=True)

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("Usage: patch.py /app/spr_online_updater.py")
    patch(Path(sys.argv[1]))
