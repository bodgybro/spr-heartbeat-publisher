# Exact deployed manual ROC function from pinned c9b6d9e104770d01809492f3d48f760faf4676f6
HELPER = '''def _roc_manual_check():
    """Run the existing ROC downloader independently of SPR/roster updates."""
    from playwright.sync_api import sync_playwright
    from datetime import datetime as roc_datetime, timedelta as roc_timedelta
    from zoneinfo import ZoneInfo as roc_ZoneInfo
    import roc_domo_daily_worker_20261104 as roc_worker
    # Scan the two most recent completed report dates. A late SharePoint
    # publication must not leave an unrecovered one-day gap forever.
    today=roc_datetime.now(roc_ZoneInfo("Australia/Sydney")).date()
    targets=[today-roc_timedelta(days=2),today-roc_timedelta(days=1)]
    _check_online_cancel()
    _set_online_progress("ROC: opening authenticated SharePoint browser")
    cfg=load_config()
    with SHAREPOINT_BROWSE_LOCK:
        try:
            with sync_playwright() as p:
                browser=_launch_sharepoint_context(
                    p,cfg,
                    headless=str(os.environ.get("SPR_HEADLESS","0")).strip().lower() in
                        ("1","true","yes","on"),
                    ignore_https_errors=True,accept_downloads=True,
                    args=["--window-size=900,650","--window-position=20,20"],
                    no_viewport=True)
                try:
                    for report_date in targets:
                        _check_online_cancel()
                        _set_online_progress("ROC: checking "+report_date.isoformat()+" in SharePoint")
                        if not roc_worker.process(browser, globals(), target_date=report_date):
                            raise RuntimeError("ROC "+report_date.isoformat()+" verification failed")
                        _check_online_cancel()
                finally:
                    browser.close()
        finally:
            _wait_for_sharepoint_profile_release()
    dates=", ".join(d.isoformat() for d in targets)
    _set_online_progress("ROC: "+dates+" verified on both websites")
    _record_online_success("roc")
    return [{"role":"ROC","message":"Reports "+dates+" checked and verified on both websites","ok":True}]
'''
