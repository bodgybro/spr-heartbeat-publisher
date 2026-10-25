#!/usr/bin/env python3
"""Add background SPR pre-indexing without changing PDF/roster upload success."""
import ast
import sys
from pathlib import Path

MARKER = "# SPR_BACKGROUND_PREINDEX_659"
EXTENSION = r'''
# SPR_BACKGROUND_PREINDEX_659
_SPR_UPLOAD_ORIGINAL=upload_pdf
_SPR_RUN_UPDATE_ORIGINAL=run_update
_SPR_INDEX_QUEUE={}
_SPR_INDEX_LOCK=threading.Lock()
_SPR_INDEX_RUNNING=threading.Lock()

def upload_pdf(site,role,pdf,cfg,page=None):
    result=_SPR_UPLOAD_ORIGINAL(site,role,pdf,cfg,page)
    try:
        import hashlib
        filename=Path(pdf).name
        match=re.fullmatch(r'All (Drivers|Guards) Combined (\d\d)_(\d\d)_(20\d\d)\.pdf',filename,re.I)
        if match and role.lower() in ('drivers','guards'):
            with Path(pdf).open('rb') as f:
                sha=hashlib.file_digest(f,'sha256').hexdigest()
            date=f'{match[4]}-{match[3]}-{match[2]}'
            roleName='driver' if role.lower()=='drivers' else 'guard'
            with _SPR_INDEX_LOCK:
                _SPR_INDEX_QUEUE[(date,roleName)]={'date':date,'role':roleName,'sha':sha,'site':site}
            print(f'  [INDEX QUEUED] {date} {roleName}',flush=True)
    except Exception as e:
        print('  [INDEX QUEUE FAILED]',e,flush=True)
    return result

def _spr_publish_index(job,page,cfg):
    import json,base64,gzip
    date,role,sha,site=job['date'],job['role'],job['sha'],job['site']
    targets=[]
    raw=os.environ.get('SPR_UPLOAD_TARGETS') or str(site or cfg.get('relay_site_url') or 'https://www.bodgybros.com/sps')
    for part in raw.split(','):
        target=canonical_spr_site(part.strip())
        # The secondary PDF mirror is handled separately to keep the primary index reliable.
        if target and 'kustomvinyls.com' not in target.lower() and target not in targets: targets.append(target)
    if not targets:targets=['https://www.bodgybros.com/sps']
    pending=[]
    for target in targets:
        endpoint=target.rstrip('/')+'/spr-index-api.php'
        try:
            response=requests.get(endpoint,params={'action':'meta','date':date,'role':role},timeout=(5,15))
            info=response.json() if response.ok else {}
            if info.get('sourceSha')==sha and info.get('parserBuild')==658 and info.get('pageLayoutBuild')==595:
                print(f'  [INDEX CURRENT] {date} {role} {target}',flush=True)
                continue
        except Exception as exc:
            print(f'  [INDEX META CHECK] {date} {role}: {exc}',flush=True)
        pending.append(target)
    if not pending:return
    page.goto(targets[0].rstrip('/')+'/',wait_until='domcontentloaded',timeout=60000)
    try:
        page.wait_for_function('typeof window.__SPR_INDEXER_API?.build === "function"',timeout=25000)
    except Exception:
        raise RuntimeError('Website must be updated to SPR Search Build 659 for pre-indexing')
    page.set_default_timeout(1500000)
    print(f'  [INDEX START] {date} {role}',flush=True)
    result=page.evaluate('o => window.__SPR_INDEXER_API.build(o.date,o.role)',{'date':date,'role':role})
    rawIndex=gzip.decompress(base64.b64decode(result['base64']))
    payload=json.loads(rawIndex)
    if (payload.get('date')!=date or payload.get('role')!=role or
        payload.get('parserBuild')!=658 or payload.get('pageLayoutBuild')!=595 or
        not payload.get('pages') or not payload.get('records') or not payload.get('shifts')):
        raise RuntimeError('Generated SPR index failed validation')
    payload['sourceSha']=sha
    compressed=gzip.compress(json.dumps(payload,separators=(',',':'),ensure_ascii=False).encode('utf-8'),compresslevel=5)
    print(f"  [INDEX BUILT] {date} {role}: {len(payload['pages'])} pages, {len(payload['records'])} runs, {len(payload['shifts'])} shifts; {len(compressed)//1024}KiB",flush=True)
    headers=_cloud_worker_headers(cfg)
    headers.update({'X-SPR-Source-Sha':sha,'Content-Type':'application/octet-stream'})
    failures=[]
    for target in pending:
        try:
            response=requests.post(target.rstrip('/')+'/spr-index-api.php',
                params={'action':'publish','date':date,'role':role},
                data=compressed,headers=headers,timeout=(10,180))
            if not response.ok or not response.json().get('ok'):
                raise RuntimeError(f'HTTP {response.status_code}: {response.text[:200]}')
            print(f'  [INDEX PUBLISHED] {date} {role} {target}',flush=True)
        except Exception as exc:failures.append(f'{target}: {exc}')
if failures:raise RuntimeError(' | '.join(failures))
    # Publish the exact same pre-built index to the secondary mirror.
    # Independent retries protect Bodgybros performance and completion reporting.
    secondary_bases=('https://www.kustomvinyls.com/sps','https://kustomvinyls.com/sps')
    secondary_error=None
    for attempt in range(1,7):
        for base in secondary_bases:
            endpoint=base+'/spr-index-api.php'
            try:
                meta=requests.get(endpoint,
                    params={'action':'meta','date':date,'role':role},
                    timeout=(8,20),allow_redirects=False)
                if meta.status_code in (301,302,303,307,308):
                    raise RuntimeError('redirected index endpoint')
                if meta.status_code==404:
                    raise RuntimeError('spr-index-api.php not installed on secondary site (HTTP 404)')
                if not meta.ok:
                    raise RuntimeError('index meta HTTP '+str(meta.status_code))
                try:info=meta.json()
                except ValueError as exc:raise RuntimeError('index meta is not JSON') from exc
                if (info.get('sourceSha')==sha and info.get('parserBuild')==658
                    and info.get('pageLayoutBuild')==595):
                    print(f'  [SECONDARY INDEX CURRENT] {date} {role} {base}',flush=True)
                    return
                posted=requests.post(endpoint,
                    params={'action':'publish','date':date,'role':role},
                    data=compressed,headers=headers,timeout=(10,180),
                    allow_redirects=False)
                try:result=posted.json()
                except ValueError:result={}
                if posted.status_code!=200 or result.get('ok') is not True:
                    raise RuntimeError(f'index publish HTTP {posted.status_code}: {posted.text[:160]}')
                print(f'  [SECONDARY INDEX PUBLISHED] {date} {role} {base}',flush=True)
                return
            except Exception as exc:
                secondary_error=f'{base}: {str(exc)[:180]}'
        if attempt<6:
            print(f'  [SECONDARY INDEX RETRY] {date} {role} attempt {attempt}: {secondary_error}',flush=True)
            time.sleep(15)
    print(f'  [SECONDARY INDEX FAILED] {date} {role}: {secondary_error}',flush=True)

def _spr_index_background(jobs):
    if not _SPR_INDEX_RUNNING.acquire(blocking=False):
        print('  [INDEX DEFERRED] Already indexing; next update can retry',flush=True)
        return
    try:
        from playwright.sync_api import sync_playwright
        cfg=load_config()
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(ignore_https_errors=True)
                for job in jobs:
                    try:_spr_publish_index(job,page,cfg)
                    except Exception as exc:
                        print(f"  [INDEX FAILED] {job['date']} {job['role']}: {exc}",flush=True)
            finally:browser.close()
    except Exception as exc:print('  [INDEX BACKGROUND ERROR]',exc,flush=True)
    finally:_SPR_INDEX_RUNNING.release()

def run_update(site, *args, **kwargs):
    try:return _SPR_RUN_UPDATE_ORIGINAL(site, *args, **kwargs)
    finally:
        # Do not delay or overwrite existing SPR + roster completion results.
        with _SPR_INDEX_LOCK:
            jobs=list(_SPR_INDEX_QUEUE.values())
            _SPR_INDEX_QUEUE.clear()
        if jobs:
            threading.Thread(target=_spr_index_background,args=(jobs,),daemon=True,name='spr-preindex').start()
'''
def apply(path):
    source=path.read_text(encoding='utf-8')
    if MARKER in source:
        print('SPR pre-index patch already applied',flush=True)
        return
    tree=ast.parse(source)
    known={x.name for x in tree.body if isinstance(x,ast.FunctionDef)}
    if not {'upload_pdf','run_update','_cloud_worker_headers'}<=known:
        raise RuntimeError('Expected existing updater methods missing')
    lines=source.splitlines(keepends=True)
    candidates=[n.lineno-1 for n in tree.body if isinstance(n,ast.If) and '__name__' in ast.get_source_segment(source,n.test)]
    if not candidates:raise RuntimeError('Updater main boundary missing')
    at=candidates[-1]
    updated=''.join(lines[:at])+EXTENSION+'\n'+''.join(lines[at:])
    compile(updated,str(path),'exec')
    path.write_text(updated,encoding='utf-8')
    print('Background SPR pre-indexing installed; checksums and verified uploads enabled',flush=True)

if __name__=='__main__':
    apply(Path(sys.argv[1]))
