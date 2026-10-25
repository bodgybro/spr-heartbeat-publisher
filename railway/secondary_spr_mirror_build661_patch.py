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

# Build 673: SFTP-only Kustom transport; physically independent website paths.
_KUSTOM_ROSTER_PROOFS={}
def _kustom_sftp_config():
    import posixpath
    required=('KUSTOM_SFTP_HOST','KUSTOM_SFTP_USERNAME',
              'KUSTOM_SFTP_PRIVATE_KEY_B64','KUSTOM_SFTP_ROOT')
    missing=[n for n in required if not os.environ.get(n,'').strip()]
    if missing:raise RuntimeError('Configure Kustom SFTP in Railway: '+', '.join(missing))
    host=os.environ['KUSTOM_SFTP_HOST'].strip()
    username=os.environ['KUSTOM_SFTP_USERNAME'].strip()
    root=posixpath.normpath(os.environ['KUSTOM_SFTP_ROOT'].strip().replace('\\','/'))
    if not root.endswith('/sps') or root in ('sps','/sps'):
        raise RuntimeError('KUSTOM_SFTP_ROOT must be the actual independent website /sps directory')
    if (host.lower()==os.environ.get('SFTP_HOST','').strip().lower()
        and username==os.environ.get('SFTP_USERNAME','').strip()
        and root==posixpath.normpath(os.environ.get('SFTP_ROOT','').strip().replace('\\','/'))):
        raise RuntimeError('Kustom SFTP root matches Bodgybros root; refusing to overwrite primary')
    return host,username,root,int(os.environ.get('KUSTOM_SFTP_PORT') or 22)

@__import__('contextlib').contextmanager
def _kustom_sftp_open():
    import paramiko,base64,io,stat
    host,username,root,port=_kustom_sftp_config()
    raw=os.environ['KUSTOM_SFTP_PRIVATE_KEY_B64'].strip()
    try:decoded=base64.b64decode(raw,validate=True).decode('utf-8')
    except Exception as exc:raise RuntimeError('Invalid base64 Kustom SFTP private key') from exc
    key=None
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=typ.from_private_key(io.StringIO(decoded));break
        except Exception:pass
    if key is None:raise RuntimeError('Unusable Kustom SFTP private key')
    hosts=DATA_ROOT/'credentials'/'kustom-sftp-known-hosts'
    hosts.parent.mkdir(parents=True,exist_ok=True)
    if not hosts.exists():hosts.write_text('',encoding='ascii');os.chmod(hosts,0o600)
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(hosts))
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sftp=None
    try:
        ssh.connect(hostname=host,port=port,username=username,pkey=key,
            timeout=10,banner_timeout=12,auth_timeout=12,
            allow_agent=False,look_for_keys=False)
        ssh.save_host_keys(str(hosts))
        sftp=ssh.open_sftp()
        sftp.get_channel().settimeout(120)
        if not stat.S_ISDIR(sftp.stat(root).st_mode):
            raise RuntimeError('Kustom /sps root is not a directory')
        yield sftp,root
    finally:
        try:
            if sftp is not None:sftp.close()
        finally:ssh.close()

def _kustom_sftp_hash(sftp,path):
    import hashlib
    digest=hashlib.sha256()
    with sftp.open(path,'rb') as stream:
        while True:
            block=stream.read(1024*1024)
            if not block:break
            digest.update(block)
    return digest.hexdigest()

def _kustom_sftp_store(sftp,root,relative,data):
    """Atomic replace after remote SHA-256 verification; leave old file on failure."""
    import posixpath,hashlib,stat
    if not isinstance(data,bytes) or not data or relative.startswith('/'):
        raise RuntimeError('Invalid Kustom SFTP data/path')
    parts=relative.split('/')
    if any(x in ('.','..','') or '\\' in x for x in parts):
        raise RuntimeError('Unsafe Kustom SFTP path')
    parent=root
    for dirname in parts[:-1]:
        parent=posixpath.join(parent,dirname)
        try:
            if not stat.S_ISDIR(sftp.stat(parent).st_mode):
                raise RuntimeError('Remote path is not a directory: '+parent)
        except FileNotFoundError:sftp.mkdir(parent)
    path=posixpath.join(root,relative)
    sha=hashlib.sha256(data).hexdigest()
    try:
        if sftp.stat(path).st_size==len(data) and _kustom_sftp_hash(sftp,path)==sha:
            return 'unchanged',sha
    except FileNotFoundError:pass
    temp=path+'.updating-'+str(os.getpid())+'-'+str(threading.get_ident())
    try:
        with sftp.open(temp,'wb') as dest:dest.write(data)
        if sftp.stat(temp).st_size!=len(data) or _kustom_sftp_hash(sftp,temp)!=sha:
            raise RuntimeError('Kustom SFTP upload checksum mismatch: '+relative)
        sftp.posix_rename(temp,path)
        if sftp.stat(path).st_size!=len(data):
            raise RuntimeError('Kustom SFTP final size mismatch: '+relative)
    finally:
        try:sftp.remove(temp)
        except Exception:pass
    return 'uploaded',sha

def _kustom_sftp_pdf(pdf,role,sha):
    name=Path(pdf).name
    relative='spr/'+('d' if role=='drivers' else 'g')+'/'+name
    with _kustom_sftp_open() as (sftp,root):
        status,remote_sha=_kustom_sftp_store(sftp,root,relative,Path(pdf).read_bytes())
    if remote_sha!=sha:raise RuntimeError('Kustom PDF source hash mismatch')
    print(f'  [KUSTOM SFTP PDF VERIFIED] {name}: {status} {sha[:12]}',flush=True)
    return status

def _kustom_sftp_roster(url,cache_path,data,sha):
    import re
    parts=str(cache_path).split('/')
    if (len(parts)<4 or len(parts)>8 or not str(cache_path).lower().endswith('.pdf') or
        any(p in ('','.','..') or not re.fullmatch(r'[A-Za-z0-9._ -]+',p) for p in parts)):
        raise RuntimeError('Invalid roster destination for SFTP: '+str(cache_path)[:120])
    with _kustom_sftp_open() as (sftp,root):
        state,received=_kustom_sftp_store(sftp,root,'rosters/'+str(cache_path),data)
    if received!=sha:raise RuntimeError('Kustom roster source hash mismatch')
    _KUSTOM_ROSTER_PROOFS[url]=(cache_path,len(data))
    print(f'    [KUSTOM SFTP ROSTER VERIFIED] {cache_path}: {state}',flush=True)

def _kustom_sftp_manifest(root_url,entries):
    import posixpath
    with _kustom_sftp_open() as (sftp,root):
        for e in entries:
            if e.get('kind')!='pdf':continue
            proof=_KUSTOM_ROSTER_PROOFS.get(e.get('url'))
            if not proof or proof[0]!=e.get('cache_path'):
                raise RuntimeError('Unverified Kustom roster PDF: '+str(e.get('name')))
            if sftp.stat(posixpath.join(root,'rosters',proof[0])).st_size!=proof[1]:
                raise RuntimeError('Missing Kustom roster before manifest: '+proof[0])
        payload=json.dumps({'root':root_url,'generated':int(time.time()),'entries':entries},
            ensure_ascii=False,separators=(',',':')).encode('utf-8')
        state,sha=_kustom_sftp_store(sftp,root,'.roster-cache/manifest.json',payload)
    print(f'  [KUSTOM SFTP ROSTER MANIFEST VERIFIED] {len(entries)} entries, {state} {sha[:12]}',flush=True)
    return {'ok':True,'entries':len(entries)}

def _kustom_sftp_index_matches(date,role,sha):
    import posixpath
    rel='spr/i/'+('d' if role=='driver' else 'g')+'/'+date
    with _kustom_sftp_open() as (sftp,root):
        try:
            with sftp.open(posixpath.join(root,rel+'.meta.json'),'rb') as reader:
                meta=json.loads(reader.read(200000).decode('utf-8'))
            size=sftp.stat(posixpath.join(root,rel+'.json.gz')).st_size
            return (meta.get('sourceSha')==sha and meta.get('parserBuild')==658
                and meta.get('pageLayoutBuild')==595 and meta.get('compressedBytes')==size and size>0)
        except FileNotFoundError:return False

def _kustom_sftp_index_publish(date,role,sha,compressed):
    import posixpath
    name=('All Drivers Combined ' if role=='driver' else 'All Guards Combined ')+date[8:10]+'_'+date[5:7]+'_'+date[:4]+'.pdf'
    relative='spr/i/'+('d' if role=='driver' else 'g')+'/'+date
    with _kustom_sftp_open() as (sftp,root):
        pdf=posixpath.join(root,'spr',('d' if role=='driver' else 'g'),name)
        if _kustom_sftp_hash(sftp,pdf)!=sha:
            raise RuntimeError('Kustom SFTP index source PDF SHA-256 mismatch')
        state,index_hash=_kustom_sftp_store(sftp,root,relative+'.json.gz',compressed)
        meta=json.dumps({'ok':True,'date':date,'role':role,'sourceSha':sha,
            'parserBuild':658,'pageLayoutBuild':595,'updatedAt':int(time.time()),
            'compressedBytes':len(compressed)},separators=(',',':')).encode('utf-8')
        _kustom_sftp_store(sftp,root,relative+'.meta.json',meta)
    print(f'  [KUSTOM SFTP INDEX VERIFIED] {date} {role}: {state} {index_hash[:12]}',flush=True)

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
            if label=='kustomvinyls':
                result[label]=_kustom_sftp_pdf(pdf,role,sha)
                continue
            raise RuntimeError('Unknown secondary SPR destination: '+label)
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
            if label=='kustomvinyls':
                _kustom_sftp_roster(url,cache_path,data,sha)
                _DUAL_ROSTER_OK[label].add(url)
                success+=1
                continue
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
            if label=='kustomvinyls':
                done[label]=_kustom_sftp_manifest(root_url,entries)
                continue
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
    _KUSTOM_ROSTER_PROOFS.clear()
    return _DUAL_ORIG_ROSTER_SYNC()

# The cross-site HTTP pull is obsolete. Kustom receives its own direct bytes.
def _spr_mirror_secondary_worker(jobs):
    print('  [CROSS-SITE PULL DISABLED] Both domains use independently uploaded SPR files',flush=True)

print('  [DUAL INDEPENDENT STORES READY] SPR and roster uploads target both websites',flush=True)
print('  [KUSTOM SFTP CODE READY] Secondary SPRs, rosters and indexes use independent SFTP; requires KUSTOM_SFTP_* settings',flush=True)

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
