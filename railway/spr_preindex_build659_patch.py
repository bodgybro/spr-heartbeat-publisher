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

def _spr_publish_index_primary_sftp(date,role,source_sha,compressed):
    """Publish a matching index and sidecar atomically via primary SFTP."""
    import base64,io,posixpath,hashlib,json
    import paramiko
    env=os.environ
    host=env.get('SFTP_HOST','').strip()
    user=env.get('SFTP_USERNAME','').strip()
    rawkey=env.get('SFTP_PRIVATE_KEY_B64','').strip()
    root=env.get('SFTP_ROOT','').strip()
    port=int(env.get('SFTP_PORT') or 22)
    if not all((host,user,rawkey,root)):
        raise RuntimeError('Primary SFTP config unavailable for index publication')
    remote_pdf_dir=_spr_remote_subdir(root,'drivers' if role=='driver' else 'guards')
    index_dir=posixpath.join(posixpath.dirname(remote_pdf_dir),'i','d' if role=='driver' else 'g')
    pdf_name=('All Drivers Combined ' if role=='driver' else 'All Guards Combined ')+date[8:10]+'_'+date[5:7]+'_'+date[:4]+'.pdf'
    remote_pdf=posixpath.join(remote_pdf_dir,pdf_name)
    remote_index=posixpath.join(index_dir,date+'.json.gz')
    remote_meta=posixpath.join(index_dir,date+'.meta.json')
    kh=DATA_ROOT/'credentials'/'spr-sftp-known_hosts'
    kh.parent.mkdir(parents=True,exist_ok=True)
    if not kh.exists():
        kh.write_text('',encoding='ascii')
        os.chmod(kh,0o600)
    key_text=base64.b64decode(rawkey).decode('utf-8')
    key=None
    for key_type in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:
            key=key_type.from_private_key(io.StringIO(key_text))
            break
        except Exception:pass
    if key is None:raise RuntimeError('Invalid primary SFTP key')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(kh))
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    tmps=[]
    try:
        ssh.connect(hostname=host,port=port,username=user,pkey=key,
            timeout=7,auth_timeout=8,banner_timeout=8,
            allow_agent=False,look_for_keys=False)
        ssh.save_host_keys(str(kh))
        with ssh.open_sftp() as sftp:
            import stat
            if not stat.S_ISREG(sftp.stat(remote_pdf).st_mode):
                raise RuntimeError('Primary PDF missing from SFTP: '+pdf_name)
            remote_sha=hashlib.sha256()
            with sftp.open(remote_pdf,'rb') as remote_input:
                while True:
                    piece=remote_input.read(1024*1024)
                    if not piece:break
                    remote_sha.update(piece)
            if remote_sha.hexdigest()!=source_sha:
                raise RuntimeError('Primary SFTP PDF does not match index source SHA-256')
            parent=posixpath.dirname(index_dir)
            for directory in (parent,index_dir):
                try:
                    st=sftp.stat(directory)
                    if not stat.S_ISDIR(st.st_mode):
                        raise RuntimeError('Index location is not a directory: '+directory)
                except FileNotFoundError:
                    sftp.mkdir(directory)
            meta_bytes=json.dumps({
                'ok':True,'date':date,'role':role,'sourceSha':source_sha,
                'parserBuild':658,'pageLayoutBuild':595,
                'updatedAt':int(time.time()),'compressedBytes':len(compressed)
            },separators=(',',':')).encode('utf-8')
            for remote,data in ((remote_index,compressed),(remote_meta,meta_bytes)):
                tmp=remote+'.updating-'+str(os.getpid())
                tmps.append(tmp)
                with sftp.open(tmp,'wb') as output:output.write(data)
                if sftp.stat(tmp).st_size!=len(data):
                    raise RuntimeError('SFTP index transfer size mismatch')
                with sftp.open(tmp,'rb') as check:
                    check_hash=hashlib.sha256()
                    while True:
                        part=check.read(1024*1024)
                        if not part:break
                        check_hash.update(part)
                if check_hash.digest()!=hashlib.sha256(data).digest():
                    raise RuntimeError('SFTP index transfer SHA-256 mismatch')
            # Write the metadata last; PHP only serves an index when it has both.
            sftp.posix_rename(tmps[0],remote_index)
            tmps.pop(0)
            sftp.posix_rename(tmps[0],remote_meta)
            tmps.pop(0)
            if sftp.stat(remote_index).st_size!=len(compressed):
                raise RuntimeError('Primary index final size mismatch')
    finally:
        try:
            if 'sftp' in locals() and tmps:
                with ssh.open_sftp() as cleanup:
                    for tmp in tmps:
                        try:cleanup.remove(tmp)
                        except Exception:pass
        except Exception:pass
        ssh.close()
    print(f'  [INDEX PUBLISHED SFTP] {date} {role}: {len(compressed)} bytes, remote SHA verified',flush=True)

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
    if not pending:
        # An unchanged primary index may still need to be seeded to the mirror.
        secondary_current=False
        for base in ('https://www.kustomvinyls.com/sps','https://kustomvinyls.com/sps'):
            try:
                reply=requests.get(base+'/spr-index-api.php',
                    params={'action':'meta','date':date,'role':role},
                    timeout=(6,15),allow_redirects=False)
                info=reply.json() if reply.status_code==200 else {}
                if (info.get('sourceSha')==sha and info.get('parserBuild')==658
                    and info.get('pageLayoutBuild')==595):
                    secondary_current=True
                    break
            except Exception:pass
        if secondary_current:
            print(f'  [INDEXES CURRENT] {date} {role}: primary and secondary',flush=True)
            return
    # Build against either website's local PDF; primary outage must not stop
    # the independent secondary from receiving its prepared index.
    index_source=None
    source_errors=[]
    for base in (targets[0],'https://www.kustomvinyls.com/sps','https://kustomvinyls.com/sps'):
        try:
            page.goto(base.rstrip('/')+'/',wait_until='domcontentloaded',timeout=35000)
            page.wait_for_function('typeof window.__SPR_INDEXER_API?.build === "function"',timeout=15000)
            index_source=base
            break
        except Exception as exc:source_errors.append(f'{base}: {str(exc)[:140]}')
    if index_source is None:
        raise RuntimeError('Neither website can build the prepared SPR index: '+' | '.join(source_errors))
    print(f'  [INDEX SOURCE] {date} {role}: {index_source}',flush=True)
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
    if failures:print('  [PRIMARY INDEX FAILED] '+' | '.join(failures),flush=True)
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
                    if failures:raise RuntimeError(' | '.join(failures))
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
                if failures:raise RuntimeError(' | '.join(failures))
                return
            except Exception as exc:
                secondary_error=f'{base}: {str(exc)[:180]}'
        if attempt<6:
            print(f'  [SECONDARY INDEX RETRY] {date} {role} attempt {attempt}: {secondary_error}',flush=True)
            time.sleep(15)
    print(f'  [SECONDARY INDEX FAILED] {date} {role}: {secondary_error}',flush=True)
    failures.append(str(secondary_error))
    if failures:raise RuntimeError(' | '.join(failures))

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

def _spr_secondary_catchup():
    """Rebuild missing indexes for the latest published date after a restart."""
    try:
        import datetime
        from zoneinfo import ZoneInfo
        from playwright.sync_api import sync_playwright
        time.sleep(25)
        if not _SPR_INDEX_RUNNING.acquire(blocking=False):
            print('  [SECONDARY INDEX CATCHUP] Already indexing; skipped',flush=True)
            return
        try:
            cfg=load_config()
            today=datetime.datetime.now(ZoneInfo('Australia/Sydney')).date()
            chosen=[]
            # Locate the newest published SPR indexes. No PDF data leaves the two sites.
            for offset in range(4):
                day=today-datetime.timedelta(days=offset)
                date=day.strftime('%Y-%m-%d')
                for role in ('driver','guard'):
                    try:
                        response=requests.get('https://www.bodgybros.com/sps/spr-index-api.php',
                            params={'action':'meta','date':date,'role':role},
                            timeout=(8,20),allow_redirects=False)
                        info=response.json() if response.status_code==200 else {}
                        sha=info.get('sourceSha','')
                        if isinstance(sha,str) and re.fullmatch('[0-9a-fA-F]{64}',sha):
                            chosen.append({'date':date,'role':role,'sha':sha,'site':'https://www.bodgybros.com/sps'})
                    except Exception as exc:
                        print(f'  [SECONDARY INDEX META] {date} {role}: {exc}',flush=True)
                if chosen:break
            if not chosen:
                print('  [SECONDARY INDEX CATCHUP] No recent indexed source PDFs; next SPR update will build indexes',flush=True)
                return
            print(f"  [SECONDARY INDEX CATCHUP] Checking {len(chosen)} indexes on {chosen[0]['date']}",flush=True)
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
                try:
                    page=browser.new_page(ignore_https_errors=True)
                    for job in chosen:
                        try:_spr_publish_index(job,page,cfg)
                        except Exception as exc:
                            print(f"  [SECONDARY INDEX CATCHUP FAILED] {job['date']} {job['role']}: {exc}",flush=True)
                finally:browser.close()
        finally:_SPR_INDEX_RUNNING.release()
    except Exception as exc:
        print('  [SECONDARY INDEX CATCHUP ERROR]',exc,flush=True)

threading.Thread(target=_spr_secondary_catchup,daemon=True,name='spr-secondary-index-catchup').start()
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
    # Install directly after the original run_update body, before its caller.
    # A preceding 'serve_forever' elsewhere in the module must not hide it.
    run_nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_update']
    if not run_nodes:raise RuntimeError('Updater run_update function not found')
    at=run_nodes[0].end_lineno
    updated=''.join(lines[:at])+EXTENSION+'\n'+''.join(lines[at:])
    compile(updated,str(path),'exec')
    path.write_text(updated,encoding='utf-8')
    print('Background SPR pre-indexing installed; checksums and verified uploads enabled',flush=True)

if __name__=='__main__':
    apply(Path(sys.argv[1]))
