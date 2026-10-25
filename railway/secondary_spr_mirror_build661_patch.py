#!/usr/bin/env python3
"""Build 661: keep Kustom Vinyls SPR PDFs synchronised using its secure mirror.

Applied after Build 659 pre-indexing and existing SFTP upload patch. No change
to primary upload success rules or the 10:00/14:00/20:00 schedule.
"""
import ast
import sys
from pathlib import Path

MARKER="# SPR_KUSTOM_SECONDARY_MIRROR_661"
EXTENSION=r'''
# SPR_KUSTOM_SECONDARY_MIRROR_661
_SPR_MIRROR_UPLOAD_ORIGINAL = upload_pdf
_SPR_MIRROR_UPDATE_ORIGINAL = run_update
_SPR_MIRROR_QUEUE = {}
_SPR_MIRROR_LOCK = threading.Lock()
_SPR_MIRROR_WORK_LOCK = threading.Lock()

def upload_pdf(site,role,pdf,cfg,page=None):
    result=_SPR_MIRROR_UPLOAD_ORIGINAL(site,role,pdf,cfg,page)
    try:
        match=re.fullmatch(r'All (Drivers|Guards) Combined (\d\d)_(\d\d)_(20\d\d)\.pdf',Path(pdf).name,re.I)
        if match and role in ('drivers','guards'):
            date=f'{match[4]}-{match[3]}-{match[2]}'
            with _SPR_MIRROR_LOCK:
                _SPR_MIRROR_QUEUE[(date,role)]={'date':date,'role':role}
    except Exception as exc:
        print('  [SECONDARY MIRROR QUEUE FAILED]',exc,flush=True)
    return result

def _spr_mirror_secondary_one(job,cfg):
    from urllib.parse import urlparse
    import requests
    date=job['date']
    role='d' if job['role']=='drivers' else 'g'
    headers=_cloud_worker_headers(cfg)
    attempts=[]
    for base in ('https://kustomvinyls.com/sps','https://www.kustomvinyls.com/sps'):
        url=base+'/spr-pdf-sync.php'
        for retry in range(2):
            try:
                r=requests.get(url,params={'date':date,'role':role,'refresh':'1'},
                    headers=headers,timeout=(12,180),stream=True,allow_redirects=False)
                try:
                    if r.status_code==200:
                        print(f'  [SECONDARY MIRRORED] {date} {job["role"]} -> {urlparse(base).hostname}',flush=True)
                        return
                    if r.status_code in (301,302,303,307,308):
                        # Do not forward updater secrets automatically to redirect targets.
                        raise RuntimeError(f'HTTP {r.status_code}: noncanonical domain; trying other known domain')
                    if r.status_code==404:
                        raise RuntimeError('Mirror PHP endpoint not yet installed on secondary site')
                    if r.status_code==401:
                        raise RuntimeError('Secondary mirror worker key rejected')
                    raise RuntimeError(f'HTTP {r.status_code}: {r.raw.read(180).decode("utf-8","replace")}')
                finally:r.close()
            except Exception as exc:
                attempts.append(f'{urlparse(base).hostname}: {exc}')
                if retry==0:
                    time.sleep(3)
    raise RuntimeError(' | '.join(attempts[-4:]))

def _spr_mirror_secondary_worker(jobs):
    if not _SPR_MIRROR_WORK_LOCK.acquire(blocking=False):
        print('  [SECONDARY MIRROR DEFERRED] Previous copy still running',flush=True)
        return
    try:
        cfg=load_config()
        for job in jobs:
            try:_spr_mirror_secondary_one(job,cfg)
            except Exception as exc:
                print(f'  [SECONDARY MIRROR FAILED] {job["date"]} {job["role"]}: {str(exc)[:500]}',flush=True)
    except Exception as exc:
        print('  [SECONDARY MIRROR WORKER ERROR]',exc,flush=True)
    finally:_SPR_MIRROR_WORK_LOCK.release()

def run_update(site):
    try:
        return _SPR_MIRROR_UPDATE_ORIGINAL(site)
    finally:
        # Separate background task: cannot invalidate successful PDF/roster transfers.
        with _SPR_MIRROR_LOCK:
            jobs=list(_SPR_MIRROR_QUEUE.values())
            _SPR_MIRROR_QUEUE.clear()
        if jobs:
            threading.Thread(target=_spr_mirror_secondary_worker,args=(jobs,),
                name='spr-secondary-mirror',daemon=True).start()
'''
def apply(path):
    src=path.read_text(encoding='utf-8')
    if MARKER in src:
        print('Secondary SPR mirror already installed',flush=True)
        return
    tree=ast.parse(src)
    funs={x.name for x in tree.body if isinstance(x,ast.FunctionDef)}
    required={'upload_pdf','run_update','_cloud_worker_headers','load_config'}
    if not required<=funs:
        raise RuntimeError(f'Expected updater functions missing: {sorted(required-funs)}')
    lines=src.splitlines(keepends=True)
    start_positions=[n.lineno-1 for n in tree.body if isinstance(n,ast.If) and '__name__' in (ast.get_source_segment(src,n.test) or '')]
    if not start_positions:raise RuntimeError('Main boundary not found')
    at=start_positions[-1]
    updated=''.join(lines[:at])+EXTENSION+'\n'+''.join(lines[at:])
    compile(updated,str(path),'exec')
    path.write_text(updated,encoding='utf-8')
    print('Secondary SPR mirroring enabled: Kustom Vinyls (authenticated, post-update)',flush=True)

if __name__=='__main__':
    apply(Path(sys.argv[1]))
