#!/usr/bin/env python3
from pathlib import Path
import sys

path=Path(sys.argv[1])
s=path.read_text(encoding="utf-8")

helper=r'''
def _fast_roster_items_from_html(raw_html, current_url):
    """Extract roster PDF targets from SharePoint page HTML without rendering it."""
    from urllib.parse import urljoin, unquote
    import html as _html
    text=_html.unescape(str(raw_html or ""))
    text=text.replace('\\u002F','/').replace('\\u002f','/').replace('\\u003A',':').replace('\\u003a',':').replace('\\/','/')
    found=[]
    pats=[
        r'https://transportcloud\\.sharepoint\\.com/sites/ST-SPS-SD/TCREW/ROSTERS[^"\'<>\\s]+?\\.pdf',
        r'/sites/ST-SPS-SD/TCREW/ROSTERS[^"\'<>\\s]+?\\.pdf',
    ]
    seen=set()
    for pat in pats:
        for raw in re.findall(pat,text,re.I):
            try:
                url=urljoin(current_url,raw).rstrip('\\')
                url=re.sub(r'(?i)(\\.pdf).*$',r'\\1',url)
                key=url.lower()
                if key in seen: continue
                seen.add(key)
                name=unquote(url.split('/')[-1].split('?')[0])
                found.append({'name':name,'url':url,'kind':'pdf'})
            except Exception:
                pass
    return found

def _run_with_hard_timeout(fn, seconds, label):
    """Run a blocking cache/upload operation with a hard wall-clock timeout."""
    import concurrent.futures
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut=pool.submit(fn)
    try:
        return fut.result(timeout=seconds)
    except concurrent.futures.TimeoutError:
        fut.cancel()
        raise TimeoutError(f"{label} timed out after {seconds}s")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

def _store_roster_fast(pdf_url,pdf_name,data,cache_path):
    last=None
    for attempt in range(2):
        try:
            return _run_with_hard_timeout(
                lambda: upload_cached_roster_pdf(pdf_url,pdf_name,data,cache_path),
                15,
                f"Roster cache upload {pdf_name}"
            )
        except Exception as e:
            last=e
            print(f"    [UPLOAD RETRY {attempt+1}/2] {pdf_name}: {e}",flush=True)
    raise RuntimeError(f"Could not store {pdf_name}: {last}")

def _download_roster_pdf_fast(page, pdf_url, pdf_name):
    """Download a roster directly with the authenticated browser request context.
    Never navigate the visible SharePoint page to a PDF viewer."""
    last=None
    for attempt in range(2):
        try:
            resp=page.context.request.get(pdf_url,timeout=10000,fail_on_status_code=False)
            body=resp.body()
            if resp.ok and body[:4]==b"%PDF":
                return body
            last=RuntimeError(f"HTTP {resp.status}")
        except Exception as e:
            last=e
        if attempt == 0:
            page.wait_for_timeout(400)
    raise RuntimeError(f"Could not download {pdf_name} directly from SharePoint: {last}")
'''

insert_at=s.rfind("def sync_all_rosters_online():")
if insert_at<0:
    raise SystemExit("sync_all_rosters_online not found")
if "def _fast_roster_items_from_html(" not in s:
    s=s[:insert_at]+helper+"\n"+s[insert_at:]

start=s.rfind("def sync_all_rosters_online():")
end=s.find("\ndef run_update(",start)
if end<0:
    raise SystemExit("run_update boundary not found")
block=s[start:end]

# Depot navigation is now a short fallback only. First fetch the page through
# Playwright's authenticated request context and extract PDF URLs from HTML.
old="""                try:
                    page.goto(depot_url,wait_until='domcontentloaded',timeout=120000)
                    page.wait_for_timeout(1200)
                    # Fast path: modern TCREW depot pages already embed all six roster
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
                except Exception as e:
                    errors.append(f"{depot_name}: {e}")
                    continue
"""
new="""                try:
                    discovered=[]
                    try:
                        rr=page.context.request.get(depot_url,timeout=8000,fail_on_status_code=False)
                        if rr.ok:
                            discovered=_fast_roster_items_from_html(rr.text(),depot_url)\n                            # SharePoint may encode these in embedded web-part JSON; parse that\n                            # from the response body without navigating the visible page.\n                            if len(discovered) < 6:\n                                try:\n                                    discovered += _sharepoint_embedded_roster_items_from_html(rr.text(),depot_url)\n                                except Exception:\n                                    pass
                    except Exception as e:
                        print(f"    Direct depot read failed quickly: {e}",flush=True)
                    missing=[f"{role} {period}" for role in roles for period in periods if not pick_pdf(discovered,role,period)]
                    if missing:
                        print(f"    Direct roster discovery missing {len(missing)} target(s); trying page for up to 8s.",flush=True)
                        _set_online_progress(f"Roster update: {depot_name} ({depot_index}/{len(depots)}) — short fallback discovery")
                        try:
                            page.goto(depot_url,wait_until='domcontentloaded',timeout=8000)
                        except Exception as nav_error:
                            try: page.evaluate("window.stop()")
                            except Exception: pass
                            print(f"    Depot page fallback stopped: {nav_error}",flush=True)
                        page.wait_for_timeout(150)
                        # Do not call the expensive DOM/frame scanners here. On a slow
                        # SharePoint page they can spend several minutes walking virtualised
                        # rows. The six PDF URLs are present in the rendered HTML once the
                        # page has loaded enough, so extract them in one cheap pass.
                        try:
                            discovered += _fast_roster_items_from_html(page.content(),depot_url)
                        except Exception as html_error:
                            print(f"    Fast rendered HTML read failed: {html_error}",flush=True)
                    missing=[f"{role} {period}" for role in roles for period in periods if not pick_pdf(discovered,role,period)]
                    if missing:
                        raise RuntimeError("Roster targets unavailable after fast discovery: "+", ".join(missing))
                    print("    Fast roster discovery found all 6 PDFs.",flush=True)
                except Exception as e:
                    try: page.evaluate("window.stop()")
                    except Exception: pass
                    errors.append(f"{depot_name}: {e}")
                    continue
"""
if old not in block:
    raise SystemExit("patched roster discovery block not found")
block=block.replace(old,new,1)

old2="""                            pdf=download_with_browser(page,{'href':pdf_url,'text':pdf_name},'Roster')
                            data=pdf.read_bytes()
                            try: pdf.unlink()
                            except Exception: pass
                            _store_roster_fast(pdf_url,pdf_name,data,cache_path)
                            pdf_count+=1
                            print(f"    [STORED] {cache_path}", flush=True)
                            # The download action can leave the page elsewhere on some
                            # SharePoint builds. Restore the depot once before the next PDF.
                            if page.url.rstrip('/') != depot_url.rstrip('/'):
                                page.goto(depot_url,wait_until='domcontentloaded',timeout=120000)
                                page.wait_for_timeout(700)
"""
new2="""                            data=_download_roster_pdf_fast(page,pdf_url,pdf_name)
                            _store_roster_fast(pdf_url,pdf_name,data,cache_path)
                            pdf_count+=1
                            print(f"    [STORED] {cache_path}", flush=True)
"""
if old2 not in block:
    raise SystemExit("roster download block not found")
block=block.replace(old2,new2,1)

s=s[:start]+block+s[end:]
path.write_text(s,encoding="utf-8")
print("Fast roster patch applied")
