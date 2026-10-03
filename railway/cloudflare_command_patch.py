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
            headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","User-Agent":"SPR-Online-Updater/619"},
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
            '                print(f"  Depot: {depot_name}", flush=True)\n                _set_online_progress(f"Roster update: {depot_name} ({depot_index}/{len(depots)} depots)")', 1)
s=s.replace('                            print(f"    [DOWNLOAD] {role} {period}: {pdf_name}", flush=True)',
            '                            _set_online_progress(f"Roster update: {depot_name} ({depot_index}/{len(depots)}) — {role} {period}")\n                            print(f"    [DOWNLOAD] {role} {period}: {pdf_name}", flush=True)', 1)
s=s.replace('                print(f"Checking {role}: today and all future dated folders...")',
            '                print(f"Checking {role}: today and all future dated folders...")\n                _set_online_progress(f"SPR update: checking {role}")', 1)
s=s.replace('                        print(f"  [DOWNLOAD] {role}: {exact_name}",flush=True)',
            '                        _set_online_progress(f"SPR update: {role} — {exact_name}")\n                        print(f"  [DOWNLOAD] {role}: {exact_name}",flush=True)', 1)

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
    global ACTIVE_ONLINE_COMMAND_ID
    endpoint=_online_control_endpoint()
    key=str(os.environ.get("SPR_COMMAND_KEY") or "")
    if not key:
        print("Online updater control disabled: SPR_COMMAND_KEY is not configured.",flush=True)
        return
    headers={"Authorization":"Bearer "+key,"User-Agent":"SPR-Online-Updater/615"}
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
                    ACTIVE_ONLINE_COMMAND_ID=tid
                    if start_background_update(scheduler_site_url(), mode=kind):
                        active_trigger=tid
                        _set_online_progress(("Roster" if kind=="rosters" else "SPR")+" update starting…")
                        print(f"Manual online {kind} update requested from Admin.",flush=True)
                    else:
                        ACTIVE_ONLINE_COMMAND_ID=""
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
