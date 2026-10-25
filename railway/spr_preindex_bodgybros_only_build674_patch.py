#!/usr/bin/env python3
"""Single-site Bodgybros background pre-indexing without touching roster uploads."""
import ast
import sys
from pathlib import Path

MARKER = "# SPR_BACKGROUND_PREINDEX_659"
EXTENSION = r'''
# SPR_BACKGROUND_PREINDEX_659
# SPR_SINGLE_SITE_BODGYBROS_674
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

def _spr_primary_index_current(date,role,sha):
    """Read the Bodgybros index metadata via existing SFTP, never HTTP."""
    import base64,io,paramiko,posixpath,json
    env=os.environ
    host=env.get('SFTP_HOST','').strip()
    user=env.get('SFTP_USERNAME','').strip()
    rawkey=env.get('SFTP_PRIVATE_KEY_B64','').strip()
    root=env.get('SFTP_ROOT','').strip()
    if not all((host,user,rawkey,root)):
        raise RuntimeError('Bodgybros SFTP settings are missing')
    base_dir=_spr_remote_subdir(root,'drivers' if role=='driver' else 'guards')
    relative='d' if role=='driver' else 'g'
    index_dir=posixpath.join(posixpath.dirname(base_dir),'i',relative)
    key_string=base64.b64decode(rawkey).decode('utf-8')
    key=None
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=typ.from_private_key(io.StringIO(key_string));break
        except Exception:pass
    if key is None:raise RuntimeError('Invalid Bodgybros SFTP private key')
    host_keys=DATA_ROOT/'credentials'/'spr-sftp-known_hosts'
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(host_keys))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=host,port=int(env.get('SFTP_PORT') or 22),
            username=user,pkey=key,timeout=7,auth_timeout=8,banner_timeout=8,
            allow_agent=False,look_for_keys=False)
        with ssh.open_sftp() as sftp:
            try:
                with sftp.open(posixpath.join(index_dir,date+'.meta.json'),'rb') as f:
                    meta=json.loads(f.read(65536).decode('utf-8'))
                index_size=sftp.stat(posixpath.join(index_dir,date+'.json.gz')).st_size
            except FileNotFoundError:return False
            return (meta.get('sourceSha')==sha and
                    meta.get('parserBuild')==658 and
                    meta.get('pageLayoutBuild')==595 and
                    meta.get('compressedBytes')==index_size and index_size>0)
    finally:ssh.close()

def _spr_publish_index(job,page,cfg):
    """Prepare and store a single-site Bodgybros index through verified SFTP."""
    import json,base64,gzip
    date,role,sha=job['date'],job['role'],job['sha']
    if role not in ('driver','guard'):raise RuntimeError('Unexpected SPR index role')
    try:
        if _spr_primary_index_current(date,role,sha):
            print(f'  [INDEX CURRENT SFTP] {date} {role} Bodgybros',flush=True)
            return
    except Exception as exc:
        print(f'  [INDEX SFTP CHECK] {date} {role}: {str(exc)[:220]}; preparing index',flush=True)
    site='https://www.bodgybros.com/sps'
    page.goto(site+'/',wait_until='domcontentloaded',timeout=45000)
    page.wait_for_function('typeof window.__SPR_INDEXER_API?.build === "function"',timeout=25000)
    page.set_default_timeout(1500000)
    print(f'  [INDEX START] {date} {role} Bodgybros',flush=True)
    result=page.evaluate('o => window.__SPR_INDEXER_API.build(o.date,o.role)',
        {'date':date,'role':role})
    raw_index=gzip.decompress(base64.b64decode(result['base64']))
    payload=json.loads(raw_index)
    if (payload.get('date')!=date or payload.get('role')!=role or
        payload.get('parserBuild')!=658 or payload.get('pageLayoutBuild')!=595 or
        not payload.get('pages') or not payload.get('records') or not payload.get('shifts')):
        raise RuntimeError('Bodgybros prepared index validation failed')
    payload['sourceSha']=sha
    compressed=gzip.compress(json.dumps(payload,separators=(',',':'),
        ensure_ascii=False).encode('utf-8'),compresslevel=5)
    print(f"  [INDEX BUILT] {date} {role}: {len(payload['pages'])} pages, {len(payload['records'])} runs, {len(payload['shifts'])} shifts; {len(compressed)//1024}KiB",flush=True)
    _spr_publish_index_primary_sftp(date,role,sha,compressed)

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
    # Install directly after the original run_update body, before its caller.
    # A preceding 'serve_forever' elsewhere in the module must not hide it.
    run_nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_update']
    if not run_nodes:raise RuntimeError('Updater run_update function not found')
    at=run_nodes[0].end_lineno
    updated=''.join(lines[:at])+EXTENSION+'\n'+''.join(lines[at:])
    compile(updated,str(path),'exec')
    path.write_text(updated,encoding='utf-8')
    print('BODGYBROS SINGLE-SITE SPR pre-indexing installed; secondary publishing disabled',flush=True)

if __name__=='__main__':
    apply(Path(sys.argv[1]))
