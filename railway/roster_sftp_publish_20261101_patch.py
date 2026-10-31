#!/usr/bin/env python3
"""Build 700: publish TCREW roster PDFs + complete manifest via verified Bodgybros SFTP.

Run AFTER all existing updater patches and BEFORE py_compile/start.sh. Do not alter
SPR publishing, SharePoint discovery, existing live roster PDFs, or schedules.
"""
import ast
import os
import sys
from pathlib import Path

MARKER = '# SPR_ROSTER_SFTP_PUBLISH_VERIFIED_20261101'

HELPERS = r'''
# Direct SFTP roster publishing: never send roster PDFs or manifests through
# the hosting security-filtered public worker-upload/worker-manifest endpoints.
def _roster_sftp_connection():
    """Reuse the already working SPR SFTP credentials and pinned host key."""
    import base64, io, posixpath, stat
    import paramiko
    host=os.environ.get('SFTP_HOST','').strip()
    user=os.environ.get('SFTP_USERNAME','').strip()
    keytext=os.environ.get('SFTP_PRIVATE_KEY_B64','').strip()
    root=os.environ.get('SFTP_ROOT','').strip()
    port=int(os.environ.get('SFTP_PORT') or 22)
    if not all((host,user,keytext,root)):
        raise RuntimeError('Bodgybros SFTP connection settings missing')
    # Same rooted location used for successfully verified SPR uploads.
    site_root=posixpath.dirname(posixpath.dirname(_spr_remote_subdir(root,'drivers')))
    keydata=base64.b64decode(keytext,validate=True).decode('utf-8')
    key=None
    for key_type in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:
            key=key_type.from_private_key(io.StringIO(keydata))
            break
        except Exception:
            pass
    if key is None:
        raise RuntimeError('Could not decode existing SFTP private key')
    known=DATA_ROOT/'credentials'/'spr-sftp-known_hosts'
    known.parent.mkdir(parents=True,exist_ok=True)
    if not known.exists(): known.write_text('',encoding='ascii')
    os.chmod(known,0o600)
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(known))
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname=host,port=port,username=user,pkey=key,
                    timeout=8,auth_timeout=10,banner_timeout=10,
                    allow_agent=False,look_for_keys=False)
        ssh.save_host_keys(str(known))
        sftp=ssh.open_sftp()
        sftp.get_channel().settimeout(40)
        try:
            # Refuse any surprise destination, e.g. another site / public_html.
            api=posixpath.join(site_root,'roster-cache-api.php')
            if not stat.S_ISREG(sftp.stat(api).st_mode):
                raise RuntimeError('SFTP target is not the Bodgybros roster store')
            return ssh,sftp,site_root
        except Exception:
            sftp.close()
            raise
    except Exception:
        ssh.close()
        raise

def _roster_sftp_dirs(sftp,site_root,parts,private=False):
    import posixpath, stat
    current=site_root
    for part in parts:
        current=posixpath.join(current,part)
        try:
            st=sftp.stat(current)
        except OSError:
            sftp.mkdir(current,mode=0o700 if private else 0o755)
            st=sftp.stat(current)
        if not stat.S_ISDIR(st.st_mode):
            raise RuntimeError('Roster SFTP target is not a directory: '+current)
    return current

def _roster_valid_cache_path(value):
    import re
    raw=str(value or '')
    if len(raw)>500 or '\\' in raw or raw.startswith('/'):
        raise RuntimeError('Unexpected roster cache path')
    parts=raw.split('/')
    if (len(parts)!=4 or not re.fullmatch(r'[a-z0-9._-]+',parts[0],re.I)
            or parts[1] not in ('drivers','guards')
            or parts[2] not in ('daily','fortnight','period')
            or not re.fullmatch(r'[A-Za-z0-9._ -]+\.pdf',parts[3],re.I)
            or any(part in ('','.','..') for part in parts)):
        raise RuntimeError('Unexpected roster cache path: '+raw[:150])
    return parts

def _roster_sftp_check_url(url):
    from urllib.parse import urlparse,unquote
    parsed=urlparse(str(url or ''))
    if (parsed.scheme.lower()!='https' or
        (parsed.hostname or '').lower()!='transportcloud.sharepoint.com' or
        '/sites/st-sps-sd/tcrew/rosters' not in unquote(parsed.path).lower()):
        raise RuntimeError('Unexpected SharePoint roster URL')

def _roster_sftp_digest(sftp,path):
    import hashlib
    digest=hashlib.sha256()
    with sftp.open(path,'rb') as file:
        while True:
            block=file.read(1024*1024)
            if not block: break
            digest.update(block)
    return digest.hexdigest()

def upload_cached_roster_pdf(url,name,data,cache_path=''):
    """Verified atomic SFTP upload, retaining the original PDF on failure."""
    import hashlib, os, posixpath, stat, time
    _roster_sftp_check_url(url)
    parts=_roster_valid_cache_path(cache_path)
    if str(name or '')!=parts[-1] or not isinstance(data,(bytes,bytearray)) or data[:4]!=b'%PDF':
        raise RuntimeError('Roster filename or PDF content does not match cache path')
    digest=hashlib.sha256(data).hexdigest()
    ssh,sftp,site_root=_roster_sftp_connection()
    tmp=None
    try:
        directory=_roster_sftp_dirs(sftp,site_root,['rosters']+parts[:-1])
        remote=posixpath.join(directory,parts[-1])
        try:
            st=sftp.stat(remote)
            if stat.S_ISREG(st.st_mode) and st.st_size==len(data):
                if _roster_sftp_digest(sftp,remote)==digest:
                    print('    [SFTP ROSTER CURRENT] '+cache_path,flush=True)
                    return {'ok':True,'complete':True,'changed':False,'bytes':len(data),'sha256':digest}
        except FileNotFoundError:
            pass
        tmp=remote+'.updating-'+str(os.getpid())+'-'+str(time.time_ns())
        with sftp.open(tmp,'wb') as output:
            for offset in range(0,len(data),1024*1024):
                output.write(data[offset:offset+1024*1024])
            output.flush()
        sftp.chmod(tmp,0o644)
        if sftp.stat(tmp).st_size!=len(data) or _roster_sftp_digest(sftp,tmp)!=digest:
            raise RuntimeError('SFTP roster temp PDF SHA-256 verification failed')
        sftp.posix_rename(tmp,remote)
        tmp=None
        if sftp.stat(remote).st_size!=len(data) or _roster_sftp_digest(sftp,remote)!=digest:
            raise RuntimeError('SFTP roster final PDF SHA-256 verification failed')
        print('    [SFTP ROSTER VERIFIED] '+cache_path+' '+digest[:12],flush=True)
        return {'ok':True,'complete':True,'changed':True,'bytes':len(data),'sha256':digest}
    finally:
        if tmp:
            try: sftp.remove(tmp)
            except Exception: pass
        try: sftp.close()
        finally: ssh.close()

def publish_roster_manifest(root_url,entries):
    """Publish full manifest only when all expected remote PDF files exist."""
    import hashlib,json,os,posixpath,stat,time
    _roster_sftp_check_url(root_url)
    if not isinstance(entries,list):
        raise RuntimeError('Roster manifest entries missing')
    clean=[]
    pdf_paths=set()
    covered=set()
    depots=set()
    for item in entries:
        if not isinstance(item,dict): raise RuntimeError('Invalid roster manifest entry')
        kind=item.get('kind')
        if kind not in ('folder','pdf'): raise RuntimeError('Unexpected roster manifest entry kind')
        _roster_sftp_check_url(item.get('url'))
        _roster_sftp_check_url(item.get('parent_url'))
        row={'name':str(item.get('name') or '')[:300],
             'url':str(item['url']),'kind':kind,'parent_url':str(item['parent_url'])}
        if kind=='pdf':
            rel=str(item.get('cache_path') or '')
            parts=_roster_valid_cache_path(rel)
            if row['name']!=parts[-1] or rel in pdf_paths:
                raise RuntimeError('Duplicate or mismatched roster manifest PDF')
            pdf_paths.add(rel)
            depots.add(parts[0])
            covered.add(tuple(parts[:3]))
            row['cache_path']=rel
        clean.append(row)
    if (not depots or len(pdf_paths)!=len(depots)*6 or
        len(covered)!=len(depots)*6):
        raise RuntimeError('Roster manifest requires six unique PDFs per depot; refusing partial publication')
    ssh,sftp,site_root=_roster_sftp_connection()
    tmp=None
    try:
        import stat
        for rel in sorted(pdf_paths):
            remote=posixpath.join(site_root,'rosters',rel)
            st=sftp.stat(remote)
            if not stat.S_ISREG(st.st_mode) or st.st_size<100 or not rel.lower().endswith('.pdf'):
                raise RuntimeError('Cannot publish manifest: remote PDF invalid: '+rel)
        cache_dir=_roster_sftp_dirs(sftp,site_root,['.roster-cache'],private=True)
        target=posixpath.join(cache_dir,'manifest.json')
        payload={'root':root_url,'generated':int(time.time()),'entries':clean}
        raw=json.dumps(payload,separators=(',',':'),ensure_ascii=False).encode('utf-8')
        local_sha=hashlib.sha256(raw).hexdigest()
        tmp=target+'.updating-'+str(os.getpid())
        with sftp.open(tmp,'wb') as out:
            out.write(raw)
            out.flush()
        sftp.chmod(tmp,0o600)
        if sftp.stat(tmp).st_size!=len(raw) or _roster_sftp_digest(sftp,tmp)!=local_sha:
            raise RuntimeError('SFTP roster manifest temp SHA-256 verification failed')
        sftp.posix_rename(tmp,target)
        tmp=None
        if sftp.stat(target).st_size!=len(raw) or _roster_sftp_digest(sftp,target)!=local_sha:
            raise RuntimeError('SFTP roster manifest final SHA-256 verification failed')
        print('[SFTP ROSTER MANIFEST VERIFIED] '+str(len(pdf_paths))+ ' PDFs, '+str(len(depots))+' depots, '+local_sha[:12],flush=True)
        return {'ok':True,'entries':len(clean),'generated':payload['generated'],
                'method':'SFTP','pdfs':len(pdf_paths)}
    finally:
        if tmp:
            try:sftp.remove(tmp)
            except Exception:pass
        try:sftp.close()
        finally:ssh.close()

def _roster_sftp_oneoff_repair():
    """User-requested one-time repair attempt; durable guard prevents restart loops."""
    import re,time
    token=str(os.environ.get('SPR_ROSTER_SFTP_REPAIR_ONCE') or '').strip()
    if not token or not re.fullmatch(r'[A-Za-z0-9_-]{1,60}',token):return
    marker=DATA_ROOT/('.roster-sftp-repair-'+token)
    if marker.exists():return
    time.sleep(8)
    try:
        site=scheduler_site_url()
        if not site:
            print('[ROSTER SFTP REPAIR] No configured site URL; next scheduled run remains available',flush=True)
            return
        if _job_snapshot().get('running'):
            print('[ROSTER SFTP REPAIR] Updater already busy; preserving normal scheduler',flush=True)
            return
        if start_background_update(site,mode='rosters'):
            marker.write_text('One-time roster repair requested: '+str(int(time.time()))+'\n',encoding='utf-8')
            print('[ROSTER SFTP REPAIR] One-time roster update started',flush=True)
    except Exception as exc:
        print('[ROSTER SFTP REPAIR] Could not start: '+str(exc)[:250],flush=True)
'''


def patch_file(path):
    source=path.read_text(encoding='utf-8')
    if MARKER in source:
        print('[ROSTER SFTP] Patch already installed',flush=True)
        return
    tree=ast.parse(source)
    funcs={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
    required={'_spr_remote_subdir','upload_cached_roster_pdf','publish_roster_manifest',
              '_store_roster_fast','sync_all_rosters_online','start_background_update',
              '_record_online_success'}
    if not required.issubset(funcs):
        raise RuntimeError('Missing expected verified SFTP/updater functions: '+str(sorted(required-funcs)))
    if '# SPR_VERIFIED_COMPLETION_REPORTING' not in source:
        raise RuntimeError('Completion guard not installed; refusing to change roster publishing')
    if 'publish_roster_manifest(root,entries)' not in source or '_store_roster_fast(pdf_url,pdf_name,data,cache_path)' not in source:
        raise RuntimeError('Roster sync implementation differs from verified baseline')
    main='if __name__=="__main__":'
    thread='    threading.Thread(target=online_control_worker,daemon=True).start()'
    if source.count(main)!=1 or source.count(thread)!=1:
        raise RuntimeError('Updater startup entrypoint differs from verified baseline')
    # Override existing global functions while leaving unrelated site logic intact.
    source=source.replace(main,HELPERS+'\n'+main,1)
    source=source.replace(thread,thread+'\n    threading.Thread(target=_roster_sftp_oneoff_repair,daemon=True).start()',1)
    source=MARKER+'\n'+source
    compile(source,str(path),'exec')
    tmp=path.with_suffix(path.suffix+'.roster-sftp-patch')
    tmp.write_text(source,encoding='utf-8')
    os.replace(tmp,path)
    print('[ROSTER SFTP PATCH READY] Verified PDF and manifest publication through Bodgybros SFTP',flush=True)

if __name__=='__main__':
    patch_file(Path(sys.argv[1]))
