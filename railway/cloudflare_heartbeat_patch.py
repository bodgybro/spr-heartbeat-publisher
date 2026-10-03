#!/usr/bin/env python3
from pathlib import Path
import sys

path=Path(sys.argv[1])
s=path.read_text(encoding="utf-8")

publish_def=r'''def publish_updater_status():
    """Publish updater heartbeat directly to the Cloudflare command Worker."""
    key=str(os.environ.get("SPR_COMMAND_KEY") or "")
    if not key:
        return False
    snap=_job_snapshot()
    running=bool(snap.get("running"))
    done=bool(snap.get("done"))
    err=str(snap.get("error") or "")
    results=snap.get("results") or []
    last_message=err or " | ".join(f"{x.get('role','')}: {x.get('message','')}" for x in results)[:1400]
    payload={
        "ok":True,
        "source":"railway-cloudflare",
        "build":623,
        "worker_online":True,
        "state":"updating" if running else ("error" if err else "idle"),
        "message":_job_message(snap),
        "progress":str(snap.get("progress") or "")[:500],
        "started_at":int(snap.get("started_at") or 0),
        "last_update":int(snap.get("completed_at") or 0),
        "last_ok":(None if not done else not bool(err)),
        "last_message":last_message,
        "schedule":["00:00","08:00","12:00","16:00","20:00"],
    }
    r=requests.post(
        _online_control_endpoint()+"/worker/heartbeat",
        headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","User-Agent":"SPR-Online-Updater/623"},
        json=payload,
        timeout=(5,20),
    )
    r.raise_for_status()
    return True

def updater_status_heartbeat_worker():
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
        time.sleep(20)
'''

def remove_top_level_func(text,name):
    marker=f"def {name}("
    start=text.find(marker)
    if start<0:
        return text
    candidates=[]
    for token in ("\ndef ","\nclass "):
        pos=text.find(token,start+1)
        if pos>=0:
            candidates.append(pos+1)
    end=min(candidates) if candidates else len(text)
    return text[:start]+text[end:]

s=remove_top_level_func(s,"publish_updater_status")
s=remove_top_level_func(s,"updater_status_heartbeat_worker")
marker="def _report_online_result("
if marker not in s:
    raise SystemExit("_report_online_result not found")
s=s.replace(marker,publish_def+"\n"+marker,1)

thread_marker='    threading.Thread(target=online_control_worker,daemon=True).start()'
if thread_marker not in s:
    raise SystemExit("online control startup thread not found")
if "threading.Thread(target=updater_status_heartbeat_worker" not in s:
    s=s.replace(thread_marker,'    threading.Thread(target=updater_status_heartbeat_worker,daemon=True).start()\n'+thread_marker,1)

path.write_text(s,encoding="utf-8")
print("Cloudflare heartbeat patch applied")
