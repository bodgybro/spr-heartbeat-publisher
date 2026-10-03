#!/usr/bin/env python3
from pathlib import Path
import sys

path=Path(sys.argv[1])
s=path.read_text(encoding="utf-8")
s=s.replace("def run_update(site):\n", "def run_update(site, include_rosters=True):\n", 1)
old='''    # Mirror all TCREW roster PDFs after the SPR browser has closed because both
    # jobs intentionally reuse the same persistent SharePoint Chrome profile.
    try:
        results.append(sync_all_rosters_online())
    except Exception as e:
        results.append({"role":"Rosters","message":"ERROR: "+str(e)})
    return results
'''
new='''    # Mirror TCREW rosters for scheduled/combined updates. Manual SPR-only
    # commands deliberately skip this so the two Admin buttons stay separate.
    if include_rosters:
        try:
            results.append(sync_all_rosters_online())
        except Exception as e:
            results.append({"role":"Rosters","message":"ERROR: "+str(e)})
    return results
'''
if old not in s:
    raise SystemExit("run_update roster tail not found")
s=s.replace(old,new,1)

# Live progress helper. It updates the local job snapshot and, for manual
# commands, sends the current step to the Cloudflare command record.
ACTIVE_HELPER='''ACTIVE_ONLINE_COMMAND_ID = ""
ONLINE_CANCEL_EVENT = threading.Event()

def _check_online_cancel():
    if ONLINE_CANCEL_EVENT.is_set():
        raise RuntimeError("Update cancelled")

def _set_online_progress(message):
    message=str(message or "")[:500]
    with JOB_LOCK:
        JOB["progress"]=message
    command_id=str(globals().get("ACTIVE_ONLINE_COMMAND_ID") or "")
    key=str(os.environ.get("SPR_COMMAND_KEY") or "")
    if not command_id or not key or not message:
        return
    try:
        requests.post(
            _online_control_endpoint()+"/worker/progress",
            headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","User-Agent":"SPR-Online-Updater/620"},
            json={"id":command_id,"progress":message},
            timeout=(5,15),
        ).raise_for_status()
    except Exception as e:
        print("Online updater progress report failed:",e,flush=True)
'''
s=s.replace("\ndef start_background_update(", "\n"+ACTIVE_HELPER+"\ndef start_background_update(", 1)

# Add useful progress checkpoints without changing the update logic.
s=s.replace("            for depot in depots:", "            for depot_index, depot in enumerate(depots, 1):", 1)
s=s.replace('                print(f"  Depot: {depot_name}", flush=True)',
            '                print(f"  Depot: {depot_name}", flush=True)\n                _check_online_cancel()\n                _set_online_progress(f"Roster update: {depot_name} ({depot_index}/{len(depots)} depots)")', 1)
s=s.replace('                            print(f"    [DOWNLOAD] {role} {period}: {pdf_name}", flush=True)',
            '                            _check_online_cancel()\n                            _set_online_progress(f"Roster update: {depot_name} ({depot_index}/{len(depots)}) — {role} {period}")\n                            print(f"    [DOWNLOAD] {role} {period}: {pdf_name}", flush=True)', 1)
s=s.replace('                print(f"Checking {role}: today and all future dated folders...")',
            '                print(f"Checking {role}: today and all future dated folders...")\n                _set_online_progress(f"SPR update: checking {role}")', 1)
s=s.replace('                        print(f"  [DOWNLOAD] {role}: {exact_name}",flush=True)',
            '                        _set_online_progress(f"SPR update: {role} — {exact_name}")\n                        print(f"  [DOWNLOAD] {role}: {exact_name}",flush=True)', 1)


# Fast roster discovery: modern TCREW depot pages embed the six roster PDF
# targets in web-part data. Use that cheap single-pass harvest first. Only run
# the expensive virtualised-DOM scrolling fallback when one or more targets
# cannot be resolved from the embedded data.
old_discovery='''                    discovered=_sharepoint_rendered_items(page,depot_url)+_sharepoint_embedded_roster_items(page,depot_url)
'''
new_discovery='''                    # Fast path: modern TCREW depot pages already embed all six roster
                    # PDF targets in their SharePoint web-part data. Harvest that once and
                    # avoid the expensive virtualised-DOM scroll when all six are present.
                    discovered=_sharepoint_embedded_roster_items(page,depot_url)
                    missing=[f"{role} {period}" for role in roles for period in periods if not pick_pdf(discovered,role,period)]
                    if missing:
                        print(f"    Fast roster discovery missing {len(missing)} target(s); using rendered fallback: {', '.join(missing)}", flush=True)
                        _set_online_progress(f"Roster update: {depot_name} ({depot_index}/{len(depots)}) — fallback discovery")
                        discovered += _sharepoint_rendered_items(page,depot_url)
                    else:
                        print("    Fast roster discovery found all 6 PDFs; rendered fallback skipped.", flush=True)
'''
if old_discovery not in s:
    raise SystemExit("roster discovery line not found")
s=s.replace(old_discovery,new_discovery,1)

# The rendered fallback is now exceptional. Cap its expensive scrolling passes
# so one malformed depot cannot stall the entire update for many minutes.
s=s.replace('''    for _ in range(40):
''','''    for _ in range(8):
''',1)

def replace_top_level_func(text,name,replacement):
    marker=f"def {name}("
    start=text.find(marker)
    if start<0: raise SystemExit(f"{name} not found")
    candidates=[]
    for token in ("\ndef ","\nclass "):
        pos=text.find(token,start+1)
        if pos>=0: candidates.append(pos+1)
    end=min(candidates) if candidates else len(text)
    return text[:start]+replacement.rstrip()+"\n\n"+text[end:]

s=replace_top_level_func(s,"_wait_for_sharepoint_signin",'''def _wait_for_sharepoint_signin(page, timeout_seconds=300):
    """Wait for interactive Microsoft sign-in and expose that state to SPR Search."""
    if _sharepoint_session_ready(page):
        return
    try:
        LOGIN_MARKER.unlink()
    except Exception:
        pass
    _set_online_progress("SharePoint sign-in required — open the online updater browser and complete Microsoft sign-in/MFA")
    print("", flush=True)
    print("============================================================", flush=True)
    print("SHAREPOINT SIGN-IN REQUIRED", flush=True)
    print("Complete Microsoft sign-in / MFA in the online updater browser.", flush=True)
    print("SPR Search will continue automatically after sign-in.", flush=True)
    print("============================================================", flush=True)
    deadline=time.time()+timeout_seconds
    while time.time()<deadline:
        if _sharepoint_session_ready(page):
            try:
                LOGIN_MARKER.write_text("SharePoint login confirmed\\n",encoding="utf-8")
            except Exception:
                pass
            _set_online_progress("SharePoint sign-in restored — continuing update")
            print("SharePoint sign-in detected. Continuing update.", flush=True)
            return
        page.wait_for_timeout(1000)
    _set_online_progress("SharePoint sign-in timed out — Microsoft sign-in/MFA is required")
    raise RuntimeError("Timed out waiting for Microsoft SharePoint sign-in/MFA on the updater browser.")''')

s=replace_top_level_func(s,"start_background_update",'''def start_background_update(site, mode="all"):
    with JOB_LOCK:
        if JOB["running"]:
            return False
        JOB.update({"running":True,"done":False,"error":None,"results":[],"mode":mode,"progress":""})
    def worker():
        try:
            if mode == "spr":
                result=run_update(site, include_rosters=False)
            elif mode == "rosters":
                result=[sync_all_rosters_online()]
            else:
                result=run_update(site, include_rosters=True)
            with JOB_LOCK:
                JOB.update({"running":False,"done":True,"results":result,"error":None})
        except Exception as e:
            with JOB_LOCK:
                JOB.update({"running":False,"done":True,"results":[],"error":str(e)})
    threading.Thread(target=worker,daemon=True).start()
    return True''')

s=replace_top_level_func(s,"_online_control_endpoint",'''def _online_control_endpoint():
    return str(os.environ.get("SPR_COMMAND_URL") or "https://spr-heartbeat-publisher.daryl-8fd.workers.dev").rstrip("/")''')

s=replace_top_level_func(s,"_job_message",'''def _job_message(snapshot=None):
    j=snapshot or _job_snapshot()
    if j.get("running"):
        return str(j.get("progress") or "SPR/roster update in progress")[:800]
    if j.get("error"):
        return str(j.get("error"))[:800]
    return "Online updater ready"''')

if "def publish_updater_status(" in s:
    s=replace_top_level_func(s,"publish_updater_status",'''def publish_updater_status():
        """Publish updater heartbeat directly to Cloudflare, not cPanel port 2083."""
        key=str(os.environ.get("SPR_COMMAND_KEY") or "")
        if not key:
            return False
        payload=_status_payload()
        snap=_job_snapshot()
        payload["build"]=620
        payload["message"]=_job_message(snap)
        payload["progress"]=str(snap.get("progress") or "")[:500]
        r=requests.post(
            _online_control_endpoint()+"/worker/heartbeat",
            headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","User-Agent":"SPR-Online-Updater/620"},
            json=payload,
            timeout=(5,20),
        )
        r.raise_for_status()
        return True''')

if "def updater_status_heartbeat_worker(" in s:
    s=replace_top_level_func(s,"updater_status_heartbeat_worker",'''def updater_status_heartbeat_worker():
        if not str(os.environ.get("SPR_COMMAND_KEY") or ""):
            print("Updater status publisher disabled: SPR_COMMAND_KEY is not configured.",flush=True)
            return
        print("Updater status publisher enabled via Cloudflare.",flush=True)
        last_error=""
        while True:
            try:
                publish_updater_status()
                last_error=""
            except Exception as e:
                msg=str(e)
                if msg!=last_error:
                    print("Cloudflare updater status publish failed:",msg,flush=True)
                    last_error=msg
            time.sleep(20)''')

s=replace_top_level_func(s,"_report_online_result",'''def _report_online_result(trigger_id=""):
    if not trigger_id:
        return
    endpoint=_online_control_endpoint()
    key=str(os.environ.get("SPR_COMMAND_KEY") or "")
    if not endpoint or not key:
        return
    j=_job_snapshot()
    ok=bool(j.get("done") and not j.get("error"))
    if j.get("error"):
        msg=str(j.get("error"))
    else:
        msg=" | ".join(f"{x.get('role','')}: {x.get('message','')}" for x in (j.get("results") or []))[:4000]
    try:
        requests.post(endpoint+"/worker/ack",headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","User-Agent":"SPR-Online-Updater/619"},json={"id":trigger_id,"ok":ok,"message":msg},timeout=(5,30)).raise_for_status()
    except Exception as e:
        print("Online updater result report failed:",e,flush=True)''')

s=replace_top_level_func(s,"online_control_worker",'''def online_control_worker():
    """Poll the Cloudflare command queue and run authenticated manual updates."""
    global ACTIVE_ONLINE_COMMAND_ID\n    endpoint=_online_control_endpoint()
    key=str(os.environ.get("SPR_COMMAND_KEY") or "")
    if not key:
        print("Online updater control disabled: SPR_COMMAND_KEY is not configured.",flush=True)
        return
    headers={"Authorization":"Bearer "+key,"User-Agent":"SPR-Online-Updater/620"}
    active_trigger=""
    print("Online updater control enabled via Cloudflare command queue.",flush=True)
    while True:
        try:
            if not active_trigger:
                r=requests.get(endpoint+"/worker/poll",headers=headers,timeout=(5,30))
                r.raise_for_status(); body=r.json()
                cmd=(body.get("command") or {}) if isinstance(body,dict) else {}
                tid=str(cmd.get("id") or "")
                kind=str(cmd.get("command") or "").lower()
                if tid and kind in ("spr","rosters"):
                    ONLINE_CANCEL_EVENT.clear()\n                    ACTIVE_ONLINE_COMMAND_ID=tid\n                    if start_background_update(scheduler_site_url(), mode=kind):
                        active_trigger=tid
                        _set_online_progress(("Roster" if kind=="rosters" else "SPR")+" update starting…")
                        print(f"Manual online {kind} update requested from Admin.",flush=True)
                    else:
                        ACTIVE_ONLINE_COMMAND_ID=""
            if active_trigger:
                try:
                    cr=requests.get(endpoint+"/worker/cancel?id="+active_trigger,headers=headers,timeout=(3,8))
                    if cr.ok and cr.json().get("cancelled"):
                        ONLINE_CANCEL_EVENT.set()
                        _set_online_progress("Cancelling update…")
                except Exception:
                    pass
            snap=_job_snapshot()
            if active_trigger and snap.get("done") and not snap.get("running"):
                _report_online_result(active_trigger)
                active_trigger=""
                ACTIVE_ONLINE_COMMAND_ID=""
        except Exception as e:
            print("Online updater control connection error:",e,flush=True)
        time.sleep(5)''')

path.write_text(s,encoding="utf-8")
print("Cloudflare command patch applied")
