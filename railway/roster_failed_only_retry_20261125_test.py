#!/usr/bin/env python3
"""No-network regression of checkpoint, same-slot retries and next-slot reset."""
from pathlib import Path
import tempfile,importlib.util,hashlib,json,types
p=Path(__file__).with_name("roster_failed_only_retry_20261125_patch.py")
spec=importlib.util.spec_from_file_location("retry",p);patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
fixture='''
# SPR_VERIFIED_COMPLETION_REPORTING
import threading
_DUAL_SITE_ROSTER_TLS=threading.local()
_DUAL_KUSTOM_ROOT="/secondary"
def _dual_enabled():return True
def _roster_valid_cache_path(path):
    assert path.count("/")==3 and path.endswith(".pdf")
def _roster_sftp_check_url(url):assert url.startswith("https://transportcloud.sharepoint.com/")
def _roster_sftp_connection():return object(),None,"/primary"
def _dual_connection():return object(),None
def _roster_sftp_release():pass
def _dual_release_connection():pass
def _download_roster_pdf_fast(page,url,name):
    downloads.append(name)
    if name in failed:raise RuntimeError("HTTP 200 not PDF")
    return b"%PDF-"+name.encode()*100
def _store_roster_fast(url,name,data,path):
    sha=hashlib.sha256(data).hexdigest()
    if name in upload_failed:
        _DUAL_SITE_ROSTER_TLS.issues["kustom"].append(name)
        return {"ok":True}
    _DUAL_SITE_ROSTER_TLS.proofs[url]=(path,len(data),sha)
    remote["/primary"][path]=sha
    remote["/secondary"][path]=sha
    return {"ok":True}
def sync_all_rosters_online():
    depots=["central","waterfall"];roles=["drivers","guards"];periods=["daily","fortnight","period"]
    expected=len(depots)*len(roles)*len(periods)
    entries=[];errors=[];pdf_count=0
    page=None
    for depot in depots:
        for role in roles:
            for period in periods:
                for once in [True]:
                    if once:
                        try:
                            pdf_name=depot+"-"+role+"-"+period+".pdf"
                            pdf_url="https://transportcloud.sharepoint.com/"+pdf_name
                            cache_path="/".join((depot,role,period,pdf_name))
                            data=_download_roster_pdf_fast(page,pdf_url,pdf_name)
                            _store_roster_fast(pdf_url,pdf_name,data,cache_path)
                            pdf_count+=1
                            entries.append(pdf_url)
                        except Exception as e:
                            errors.append(str(e))
    all_ok=bool(expected and not errors and pdf_count==expected)
    if all_ok:
        assert len(_DUAL_SITE_ROSTER_TLS.proofs)==expected
        assert len(entries)==expected
        if any(_DUAL_SITE_ROSTER_TLS.issues.values()):
            raise RuntimeError("manifest failure")
        manifests.append(entries)
    msg=f"{pdf_count}/{expected} roster PDFs downloaded and stored across {len(depots)} depots"
    return {"role":"Rosters","message":msg,"ok":all_ok,"files_expected":expected,
            "files_downloaded":pdf_count,"files_uploaded":pdf_count,
            "files_failed":max(expected-pdf_count,len(errors))}
_base=sync_all_rosters_online
def sync_all_rosters_online():
    _DUAL_SITE_ROSTER_TLS.proofs={}
    _DUAL_SITE_ROSTER_TLS.issues={"bodgybros":[],"kustom":[]}
    try:return _base()
    finally:
        _DUAL_SITE_ROSTER_TLS.proofs={}
        _DUAL_SITE_ROSTER_TLS.issues={}
if __name__=="__main__":pass
'''
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/"updater.py";path.write_text(fixture);patch.apply(path)
    once=path.read_text();patch.apply(path);assert once==path.read_text()
    failed={f"waterfall-{r}-{k}.pdf" for r in ("drivers","guards") for k in ("daily","period","fortnight")}
    downloads=[];manifests=[];remote={"/primary":{},"/secondary":{}}
    env={"__name__":"test","DATA_ROOT":Path(tmp),"downloads":downloads,"manifests":manifests,
         "failed":failed,"upload_failed":set(),"remote":remote,"hashlib":hashlib}
    exec(compile(once,str(path),"exec"),env)
    slot=["2026-11-25T22:00:00+11:00"];env["_rr_slot"]=lambda:slot[0]
    env["_rr_remote_verify"]=lambda ssh,root,rows:{k for k,v in rows.items() if remote[root].get(k)==v["sha"]}
    run=env["sync_all_rosters_online"]
    first=run();assert not first["ok"] and len(downloads)==12
    assert len(json.loads(env["_rr_path"]().read_text())["rows"])==6
    downloads.clear();failed.clear()
    second=run();assert second["ok"] and len(downloads)==6 and all(x.startswith("waterfall") for x in downloads)
    assert second["files_reused"]==6 and second["files_downloaded"]==6 and len(manifests)==1
    assert not env["_rr_path"]().exists()
    # Fingerprint mismatch on one host must be retried, never counted as complete.
    failed.add("waterfall-drivers-daily.pdf");downloads.clear();assert not run()["ok"]
    remote["/secondary"]["central/drivers/daily/central-drivers-daily.pdf"]="wrong"
    downloads.clear();failed.clear();third=run()
    assert third["ok"] and set(downloads)=={"waterfall-drivers-daily.pdf","central-drivers-daily.pdf"}
    # A new normal scheduled slot always starts a fresh full update.
    failed.add("waterfall-drivers-daily.pdf");assert not run()["ok"]
    slot[0]="2026-11-26T08:00:00+11:00";downloads.clear();failed.clear()
    fourth=run();assert fourth["ok"] and len(downloads)==12 and fourth["files_reused"]==0
    # One-site upload failure cannot create a checkpoint for that file.
    failed.add("waterfall-drivers-daily.pdf")
    env["upload_failed"].add("central-drivers-daily.pdf")
    assert not run()["ok"]
    state=json.loads(env["_rr_path"]().read_text())
    assert "central/drivers/daily/central-drivers-daily.pdf" not in state["rows"]
    env["upload_failed"].clear();failed.clear();downloads.clear()
    assert run()["ok"] and set(downloads)=={"waterfall-drivers-daily.pdf","central-drivers-daily.pdf"}
print("ROSTER_FAILED_ONLY_RETRY_TEST_PASS failed_only=yes dual_fingerprint=yes next_slot_full=yes one_site_failure_retried=yes manifest_complete=yes")
