#!/usr/bin/env python3
"""SPR Search Build 700: remove invalid one-letter From-To locations.

Read current working versioned JS and HTML via existing pinned Bodgybros SFTP.
Guard exact source SHA and module imports, only modify populateFromToLocations.
Stage and verify new physical JS filename + HTML to bypass mobile stale cache.
Retain all SPR PDFs, original shift links, mobile roster memory fix and updater.
"""
import os,io,base64,posixpath,hashlib,shutil,tempfile,subprocess
from pathlib import Path
import paramiko

OLD_JS='script-700-mobile-224-3nov-v1.js'
NEW_JS='script-700-fromto-locations-v1.js'
EXPECTED_SHA='d6ba623f24e6910fc4c5d2f88b7e628cbd9e0b9a692a1418d1e7742964592cbb'
MARKER='SPR_FROM_TO_FILTER_ONE_CHAR_20261102'
ORIGINAL="    let v=cleanPrepStableLocation(value)||clean(value||'');"
REPLACEMENT="""    let v=cleanPrepStableLocation(value)||clean(value||'');
    // SPR_FROM_TO_FILTER_ONE_CHAR_20261102
    // The SPR PDF sometimes exposes a lone table/line marker, such as "N".
    // Single letters are not selectable station/depot names.
    // Preserve valid entries such as Narwee, Newtown and North Sydney.
    if(/^[A-Za-z]$/.test(v.trim()))return '';"""

def sha(data):return hashlib.sha256(data).hexdigest()

def root_path():
    root=os.environ['SFTP_ROOT'].replace('\\','/').rstrip('/')
    if root.endswith('/sps/spr'):return root[:-4]
    if root.endswith('/sps'):return root
    if root=='public_html' or root.endswith('/public_html'):return root+'/sps'
    raise RuntimeError('Unexpected Bodgybros SFTP root')

def read(ftp,path):
    with ftp.open(path,'rb') as file:return file.read()

def write(ftp,path,data):
    with ftp.open(path,'wb') as file:
        for start in range(0,len(data),1048576):file.write(data[start:start+1048576])
        file.flush()

def patched_js(source):
    if sha(source.encode('utf-8'))!=EXPECTED_SHA:
        raise RuntimeError('Working JS source SHA changed, refusing patch')
    js=source
    if MARKER in js:raise RuntimeError('Already patched, refusing double injection')
    for guard in ('function populateFromToLocations(){',
                  'function fromToPoint(',
                  'function renderCard(r){',
                  'SPR_MOBILE_224_NOV3_FIX_20261102',
                  'SPR_578B_LOCATION_DISPLAY_V3_20261101',
                  '// SPR_SORT_RUN_START_20261101'):
        if guard not in js:raise RuntimeError('Required working behavior absent: '+guard)
    start=js.index('function populateFromToLocations(){')
    end=js.index('function fromToPoint(',start)
    section=js[start:end]
    if section.count(ORIGINAL)!=1:
        raise RuntimeError('From-To location normalization differs from inspected source')
    section=section.replace(ORIGINAL,REPLACEMENT,1)
    revised=js[:start]+section+js[end:]
    if revised.count(MARKER)!=1:
        raise RuntimeError('Location filter marker was not installed exactly once')
    return revised.encode('utf-8')

def verify_js(data):
    node=shutil.which('node')
    if not node:
        import importlib.util
        p=importlib.util.find_spec('playwright')
        if p and p.submodule_search_locations:
            candidate=Path(list(p.submodule_search_locations)[0])/'driver'/'node'
            if candidate.is_file():node=str(candidate)
    if not node:raise RuntimeError('JavaScript syntax checker missing')
    with tempfile.NamedTemporaryFile(mode='wb',suffix='.js',delete=False) as f:
        f.write(data);path=f.name
    try:
        check=subprocess.run([node,'--check',path],text=True,capture_output=True,timeout=20)
        if check.returncode:
            raise RuntimeError('Generated JS failed syntax check: '+check.stderr[:350])
        print('[FROM-TO JS SYNTAX VERIFIED]',flush=True)
    finally:os.unlink(path)
    # A minimal self-check for the exact value guard.
    if b"if(/^[A-Za-z]$/.test(v.trim()))return '';" not in data:
        raise RuntimeError('Single letter filter missing')

def main():
    keytext=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(keytext));break
        except Exception:pass
    if key is None:raise RuntimeError('Working SFTP key missing')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ['SFTP_HOST'],username=os.environ['SFTP_USERNAME'],
                port=int(os.environ.get('SFTP_PORT') or 22),
                pkey=key,timeout=12,auth_timeout=12,banner_timeout=12,
                allow_agent=False,look_for_keys=False)
    ftp=ssh.open_sftp()
    site=root_path()
    originals={};updated={};staged=[];published=[]
    try:
        old=read(ftp,posixpath.join(site,OLD_JS))
        if sha(old)!=EXPECTED_SHA:
            raise RuntimeError('Live JS changed; no site writes. Actual SHA: '+sha(old)[:20])
        original_script=read(ftp,posixpath.join(site,'script.js'))
        originals['script.js']=original_script
        originals[OLD_JS]=old
        for name in ('index.php','index.html'):
            originals[name]=read(ftp,posixpath.join(site,name))
        try:
            ftp.stat(posixpath.join(site,NEW_JS))
            raise RuntimeError('Versioned output filename exists; not overwriting')
        except FileNotFoundError:
            pass
        changed=patched_js(old.decode('utf-8'))
        verify_js(changed)
        updated[NEW_JS]=changed
        if sha(original_script)==sha(old):
            updated['script.js']=changed
        else:
            print('[FROM-TO NOTE] Root script.js differs; preserving root file',flush=True)
        for name in ('index.php','index.html'):
            text=originals[name].decode('utf-8')
            old_import='./'+OLD_JS
            if text.count(old_import)!=1 or 'class="build-number">Build 700' not in text:
                raise RuntimeError('Unexpected working HTML module import: '+name)
            updated[name]=text.replace(old_import,'./'+NEW_JS,1).encode('utf-8')
        print('[FROM-TO SOURCE VERIFIED] Current Build 700 source matched exact SHA',flush=True)
        for name,data in updated.items():
            target=posixpath.join(site,name)
            temporary=target+'.fromto-stage-'+str(os.getpid())
            write(ftp,temporary,data)
            if sha(read(ftp,temporary))!=sha(data):
                raise RuntimeError('Staged SHA-256 verification failed: '+name)
            ftp.chmod(temporary,0o644)
            staged.append((name,target,temporary))
        steps=[NEW_JS]+(['script.js'] if 'script.js' in updated else [])+['index.php','index.html']
        lookup={name:(target,temp) for name,target,temp in staged}
        try:
            for name in steps:
                target,temp=lookup[name]
                ftp.posix_rename(temp,target)
                published.append(name)
                if sha(read(ftp,target))!=sha(updated[name]):
                    raise RuntimeError('Published SHA-256 verification failed: '+name)
                print('[FROM-TO LIVE VERIFIED]',name,sha(updated[name])[:16],flush=True)
            print('[FROM-TO PATCH COMPLETE] Invalid single-letter options including N filtered; existing searches/PDFs unchanged',flush=True)
        except Exception:
            for name in reversed(published):
                target=posixpath.join(site,name)
                if name==NEW_JS:
                    ftp.remove(target)
                else:
                    temp=target+'.fromto-rollback-'+str(os.getpid())
                    write(ftp,temp,originals[name])
                    ftp.posix_rename(temp,target)
                print('[FROM-TO PATCH ROLLBACK]',name,flush=True)
            raise
    finally:
        for name,target,temp in staged:
            try:ftp.remove(temp)
            except Exception:pass
        ftp.close();ssh.close()

if __name__=='__main__':
    main()
