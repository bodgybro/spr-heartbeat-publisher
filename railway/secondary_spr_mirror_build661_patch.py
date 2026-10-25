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
                    headers=headers,timeout=(12,180),stream=True,allow_redirects=False,verify=False)
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

def run_update(site, *args, **kwargs):
    try:
        return _SPR_MIRROR_UPDATE_ORIGINAL(site, *args, **kwargs)
    finally:
        # Separate background task: cannot invalidate successful PDF/roster transfers.
        with _SPR_MIRROR_LOCK:
            jobs=list(_SPR_MIRROR_QUEUE.values())
            _SPR_MIRROR_QUEUE.clear()
        if jobs:
            threading.Thread(target=_spr_mirror_secondary_worker,args=(jobs,),
                name='spr-secondary-mirror',daemon=True).start()

# Bind the same keyword used by manual and scheduled commands against every
# stage of the *runtime* call chain, without actually running any update.
def _spr_verify_update_chain():
    import inspect
    members=(
        ('active',run_update),
        ('mirror base',_SPR_MIRROR_UPDATE_ORIGINAL),
        ('pre-index base',_SPR_RUN_UPDATE_ORIGINAL),
    )
    for label,func in members:
        try:inspect.signature(func).bind('https://www.bodgybros.com/sps',include_rosters=False)
        except TypeError as exc:
            raise RuntimeError(f'SPR updater keyword test failed at {label}: {exc}') from exc
    print('  [SPR UPDATE ARGUMENT TEST PASSED] manual and scheduled SPR-only calls accept include_rosters=False',flush=True)
_spr_verify_update_chain()

# SPR_DUAL_LOCAL_PUBLISH_670
import hashlib as _dual_hashlib
_DUAL_HOSTS={
 'bodgybros':('https://www.bodgybros.com/sps','https://bodgybros.com/sps'),
 'kustomvinyls':('https://www.kustomvinyls.com/sps','https://kustomvinyls.com/sps'),
}
_DUAL_HOST_CACHE={}
_DUAL_ROSTER_OK={k:set() for k in _DUAL_HOSTS}
_DUAL_ROSTER_ERRORS={k:[] for k in _DUAL_HOSTS}
_DUAL_ORIG_ROSTER_SYNC=sync_all_rosters_online

def _dual_tls_verify(label):
    # Explicit site-specific exception. Never disable verification globally.
    return label != 'kustomvinyls'

def _dual_host(label,api,params):
    urls=list(_DUAL_HOSTS[label])
    previous=_DUAL_HOST_CACHE.get(label)
    if previous in urls:urls.remove(previous);urls.insert(0,previous)
    failures=[]
    for base in urls:
        try:
            r=requests.get(base+'/'+api,params=params,timeout=(6,15),allow_redirects=False,verify=_dual_tls_verify(label))
            try: body=r.json()
            except ValueError:body={}
            if r.status_code in (200,404) and isinstance(body,dict) and 'ok' in body:
                _DUAL_HOST_CACHE[label]=base
                return base,body
            failures.append(f'{base}: HTTP {r.status_code}')
        except Exception as e:failures.append(f'{base}: {str(e)[:100]}')
    raise RuntimeError(f'{label} endpoint missing or offline: '+ '; '.join(failures))

def upload_pdf(site,role,pdf,cfg,page=None):
    """Check and publish one downloaded SPR PDF independently on both sites."""
    import math
    name=Path(pdf).name
    match=re.fullmatch(r'All (Drivers|Guards) Combined (\d\d)_(\d\d)_(20\d\d)\.pdf',name,re.I)
    if not match or role not in ('drivers','guards'):
        raise RuntimeError('SPR name/role mismatch: '+name)
    date=f'{match[4]}-{match[3]}-{match[2]}'
    index_role='driver' if role=='drivers' else 'guard'
    sha=_dual_hashlib.sha256(Path(pdf).read_bytes()).hexdigest()
    size=Path(pdf).stat().st_size
    errors=[];result={}
    with _SPR_INDEX_LOCK:
        _SPR_INDEX_QUEUE[(date,index_role)]={'date':date,'role':index_role,'sha':sha,
            'site':'https://www.bodgybros.com/sps'}
    for label in _DUAL_HOSTS:
        try:
            params={'action':'meta','date':date,'role':index_role}
            if label=='bodgybros':
                # Bodgybros has always used SFTP with cPanel as fallback.
                # Do NOT call PHP/HTTP to decide whether an SFTP transfer succeeded.
                try:
                    _spr_upload_over_sftp(role,pdf)
                    result[label]='SFTP SHA-256 verified'
                    print(f'  [SPR STORED SFTP VERIFIED] {label} {date} {index_role}: {size} bytes',flush=True)
                except Exception as sftp_error:
                    if 'SHA-256 mismatch' in str(sftp_error):
                        raise
                    print('  [SPR SFTP UNAVAILABLE] '+str(sftp_error)[:200]+'; trying direct cPanel',flush=True)
                    _spr_upload_over_cpanel(role,pdf)
                    result[label]='cPanel API upload acknowledged (SHA-256 not independently checked)'
                    print(f'  [SPR STORED CPANEL ACKNOWLEDGED] {label} {date} {index_role}',flush=True)
                continue
            base,meta=_dual_host(label,'spr-dual-publish-api.php',params)
            if meta.get('sha256')==sha and meta.get('size')==size:
                result[label]='unchanged'
                print(f'  [SPR VERIFIED UNCHANGED] {label} {date} {index_role}',flush=True)
                continue
            if label=='kustomvinyls':
                count=max(1,math.ceil(size/(1024*1024)))
                with Path(pdf).open('rb') as source:
                    for i in range(count):
                        chunk=source.read(1024*1024)
                        for attempt in range(3):
                            try:
                                r=requests.post(base+'/spr-dual-publish-api.php',
                                    params={'action':'upload-chunk','date':date,'role':index_role},
                                    headers=_cloud_worker_headers(cfg),
                                    data={'sha256':sha,'index':str(i),'total':str(count)},
                                    files={'chunk':('chunk.bin',chunk,'application/octet-stream')},
                                    timeout=(10,90),allow_redirects=False,verify=_dual_tls_verify(label))
                                try:j=r.json()
                                except ValueError:j={}
                                if not r.ok or not j.get('ok'):
                                    raise RuntimeError(f'HTTP {r.status_code} '+str(j.get('error') or r.text[:120]))
                                if i==count-1 and (j.get('sha256')!=sha or j.get('size')!=size):
                                    raise RuntimeError('SPR final size or checksum mismatch')
                                break
                            except Exception:
                                if attempt==2:raise
                                time.sleep(attempt+2)
            # Verify the secondary PDF is now stored locally, not proxied.
            if label in _DUAL_HOSTS:
                r=requests.get(base+'/spr-dual-publish-api.php',
                    params=params,timeout=(6,25),allow_redirects=False,verify=_dual_tls_verify(label))
                j=r.json() if r.status_code==200 else {}
                if j.get('sha256')!=sha or j.get('size')!=size:
                    raise RuntimeError('Post-upload local SPR verification failed')
            result[label]='uploaded'
            print(f'  [SPR STORED] {label} {date} {index_role}: {size} bytes',flush=True)
        except Exception as e:
            errors.append(label+': '+str(e)[:260])
            print('  [SPR PUBLISH FAILED] '+errors[-1],flush=True)
    if errors:raise RuntimeError('SPR copies incomplete: '+' | '.join(errors))
    return result

def upload_cached_roster_pdf(url,name,data,cache_path=''):
    """One SharePoint download; independent checksum-checked uploads to both stores."""
    import math
    if not data.startswith(b'%PDF'):raise RuntimeError('Downloaded roster is not PDF: '+name)
    sha=_dual_hashlib.sha256(data).hexdigest()
    success=0
    for label in _DUAL_HOSTS:
        try:
            base,_=_dual_host(label,'roster-cache-api.php',{'action':'health'})
            endpoint=base+'/roster-cache-api.php'
            headers=_cache_headers()
            r=requests.get(endpoint,params={'action':'worker-check','url':url,'cache_path':cache_path},
                headers=headers,timeout=(8,20),allow_redirects=False,verify=_dual_tls_verify(label))
            try:check=r.json()
            except ValueError:check={}
            if r.status_code==200 and check.get('sha256')==sha and check.get('size')==len(data):
                print(f'    [ROSTER VERIFIED UNCHANGED] {label} {cache_path}',flush=True)
            else:
                if r.status_code not in (200,404):
                    raise RuntimeError('Roster check failed HTTP '+str(r.status_code))
                chunk_size=1024*1024
                count=max(1,math.ceil(len(data)/chunk_size))
                for i in range(count):
                    part=data[i*chunk_size:(i+1)*chunk_size]
                    for attempt in range(3):
                        try:
                            reply=requests.post(endpoint,params={'action':'worker-upload'},
                                headers=headers,data={'url':url,'filename':name,
                                'cache_path':cache_path,'index':str(i),'total':str(count)},
                                files={'chunk':('chunk.bin',part,'application/octet-stream')},
                                timeout=(10,50),allow_redirects=False,verify=_dual_tls_verify(label))
                            try:j=reply.json()
                            except ValueError:j={}
                            if not reply.ok or not j.get('ok'):
                                raise RuntimeError('Roster chunk HTTP '+str(reply.status_code)+': '+str(j.get('error') or reply.text[:90]))
                            if i==count-1 and (j.get('sha256')!=sha or j.get('bytes')!=len(data)):
                                raise RuntimeError('Roster final checksum or length mismatch')
                            break
                        except Exception:
                            if attempt==2:raise
                            time.sleep(attempt+2)
                print(f'    [ROSTER STORED] {label} {cache_path}',flush=True)
            _DUAL_ROSTER_OK[label].add(url)
            success+=1
        except Exception as e:
            err=name+': '+str(e)[:200]
            _DUAL_ROSTER_ERRORS[label].append(err)
            print(f'    [ROSTER SITE FAILED] {label}: {err}',flush=True)
    if not success:raise RuntimeError('Both roster destinations failed: '+name)
    return {'ok':True,'sites':success}

def publish_roster_manifest(root_url,entries):
    """Publish separate manifests only after each host has every expected PDF."""
    depots=[e for e in entries if e.get('kind')=='folder' and e.get('parent_url')==root_url]
    pdfs=[e for e in entries if e.get('kind')=='pdf']
    if not depots or len(pdfs)!=len(depots)*6:
        raise RuntimeError(f'Incomplete roster source: {len(pdfs)} PDFs for {len(depots)} depots; expected six per depot. Old manifests retained.')
    expected={e['url'] for e in pdfs}
    errors=[];done={}
    for label in _DUAL_HOSTS:
        missing=expected-_DUAL_ROSTER_OK[label]
        if missing or _DUAL_ROSTER_ERRORS[label]:
            errors.append(f'{label}: {len(missing)} missing PDFs, {len(_DUAL_ROSTER_ERRORS[label])} errors')
            continue
        try:
            base,_=_dual_host(label,'roster-cache-api.php',{'action':'health'})
            endpoint=base+'/roster-cache-api.php'
            r=requests.post(endpoint,params={'action':'worker-manifest'},
                headers={**_cache_headers(),'Content-Type':'application/json'},
                data=json.dumps({'root':root_url,'generated':int(time.time()),'entries':entries}),
                timeout=(10,110),allow_redirects=False,verify=_dual_tls_verify(label))
            j=r.json() if r.status_code==200 else {}
            if not r.ok or not j.get('ok') or j.get('entries')!=len(entries):
                raise RuntimeError('Manifest HTTP '+str(r.status_code)+': '+str(j.get('error') or r.text[:130]))
            verify=requests.get(endpoint,params={'action':'root'},timeout=(6,30),allow_redirects=False,verify=_dual_tls_verify(label))
            proof=verify.json() if verify.status_code==200 else {}
            if proof.get('url')!=root_url or len(proof.get('items',[]))!=len(depots):
                raise RuntimeError('Local roster manifest verification failed')
            done[label]=j
            print(f'  [ROSTER MANIFEST VERIFIED] {label}: {len(pdfs)} PDFs',flush=True)
        except Exception as e:errors.append(label+': '+str(e)[:180])
    if errors:raise RuntimeError('Incomplete independent roster stores: '+' | '.join(errors))
    return done

def sync_all_rosters_online():
    for key in _DUAL_HOSTS:
        _DUAL_ROSTER_OK[key].clear()
        _DUAL_ROSTER_ERRORS[key].clear()
    return _DUAL_ORIG_ROSTER_SYNC()

# The cross-site HTTP pull is obsolete. Kustom receives its own direct bytes.
def _spr_mirror_secondary_worker(jobs):
    print('  [CROSS-SITE PULL DISABLED] Both domains use independently uploaded SPR files',flush=True)

print('  [DUAL INDEPENDENT STORES READY] SPR and roster uploads target both websites',flush=True)
print('  [KUSTOM TLS EXCEPTION] Certificate verification disabled only for Kustom Vinyls HTTPS requests',flush=True)

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
    # Protect established primary transport across future patch revisions.
    required_primary={'_spr_upload_over_sftp','_spr_upload_over_cpanel',
        '_spr_publish_index_primary_sftp'}
    if not required_primary<=funs:
        raise RuntimeError('Primary SFTP PDF and index transfer paths missing; refusing deployment')
    if 'SFTP remote PDF SHA-256 mismatch' not in src:
        raise RuntimeError('Primary SFTP checksum validation missing; refusing deployment')
    lines=src.splitlines(keepends=True)
    start_positions=[n.lineno-1 for n in tree.body if isinstance(n,ast.If) and '__name__' in (ast.get_source_segment(src,n.test) or '')]
    if not start_positions:raise RuntimeError('Main boundary not found')
    # Install directly after the last effective run_update wrapper. This
    # guarantees that the new definitions execute before the server starts.
    run_nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_update']
    if not run_nodes:raise RuntimeError('Updater run_update function not found')
    preindex=[n for n in run_nodes if '_SPR_RUN_UPDATE_ORIGINAL' in (ast.get_source_segment(src,n) or '')]
    if len(preindex)!=1:raise RuntimeError('Expected exactly one pre-index run_update wrapper')
    at=preindex[0].end_lineno
    updated=''.join(lines[:at])+EXTENSION+'\n'+''.join(lines[at:])
    # Every wrapper must forward include_rosters to a base function that accepts it.
    # The older Cloudflare patch can change the roster body without changing its
    # signature when the original definition is formatted differently.
    parsed=ast.parse(updated)
    updated_lines=updated.splitlines(keepends=True)
    base_checked=False
    repairs=[]
    for node in parsed.body:
        if not isinstance(node,ast.FunctionDef) or node.name!='run_update':
            continue
        params=node.args
        named=[a.arg for a in params.posonlyargs+params.args+params.kwonlyargs]
        accepts='include_rosters' in named or params.kwarg is not None
        reads_flag=any(isinstance(item,ast.Name) and item.id=='include_rosters' for item in ast.walk(node))
        print(f'  [RUN_UPDATE CHECK] line {node.lineno}: params={named}; accepts_flag={accepts}; uses_flag={reads_flag}',flush=True)
        if accepts:
            if 'include_rosters' in named:base_checked=True
            continue
        if not reads_flag:
            raise RuntimeError('run_update does not accept or use include_rosters; cannot safely disable roster work')
        line=updated_lines[node.lineno-1]
        if line.strip()!='def run_update(site):':
            raise RuntimeError('run_update has an unsupported signature and cannot be repaired safely')
        updated_lines[node.lineno-1]=line.replace('def run_update(site):','def run_update(site, include_rosters=True):',1)
        repairs.append(node.lineno)
        base_checked=True
    if not base_checked:
        raise RuntimeError('run_update signature validation failed: no base implementation accepts include_rosters')
    updated=''.join(updated_lines)
    parsed_proof=ast.parse(updated)
    live_main=[n.lineno for n in parsed_proof.body if isinstance(n,ast.If) and
        '__name__' in (ast.get_source_segment(updated,n.test) or '') and
        'serve_forever' in (ast.get_source_segment(updated,n) or '')]
    print(f'  [DUAL INSTALL DIAGNOSTIC] insertion_at={at+1}; serve_main={live_main}; inserted_marker={updated.count("# SPR_DUAL_LOCAL_PUBLISH_670")}',flush=True)
    compile(updated,str(path),'exec')
    print(f'  [RUN_UPDATE VALIDATED] include_rosters forwarded; base signature repairs={repairs}',flush=True)
    path.write_text(updated,encoding='utf-8')
    print('Secondary SPR mirroring enabled: Kustom Vinyls (authenticated, post-update)',flush=True)

if __name__=='__main__':
    apply(Path(sys.argv[1]))
