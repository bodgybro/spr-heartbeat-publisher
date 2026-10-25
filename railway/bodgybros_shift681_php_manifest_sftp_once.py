#!/usr/bin/env python3
"""Build 681: fix Bodgybros fast Shift PDF manifest HTTP 406.
Installs a small read-only PHP manifest reader, points only the prepared Shift
cache lookup to it, and leaves original shift PDF files and updater untouched.
"""
import os,io,base64,posixpath,hashlib,re,urllib.request
from pathlib import Path
import paramiko,requests

PHP_URL='https://raw.githubusercontent.com/bodgybro/spr-heartbeat-publisher/3abd24b0c989a7490f2d2c6c71125acf233ba417/railway/spr_shift_cache_readonly_build681.php'
MARK='// SPR_SHIFT_CACHE_PHP_681'
def sha(data):return hashlib.sha256(data).hexdigest()
def read(sftp,path):
    with sftp.open(path,'rb') as stream:return stream.read()
def atomic(sftp,path,old,new):
    if old is not None and sha(read(sftp,path))!=sha(old):
        raise RuntimeError('Concurrent website change: '+posixpath.basename(path))
    tmp=path+'.build681-new'
    try:
        with sftp.open(tmp,'wb') as stream:stream.write(new)
        if sha(read(sftp,tmp))!=sha(new):
            raise RuntimeError('Temporary SFTP SHA-256 verification failed')
        sftp.posix_rename(tmp,path)
        if sha(read(sftp,path))!=sha(new):
            raise RuntimeError('Final SFTP SHA-256 verification failed')
    finally:
        try:sftp.remove(tmp)
        except Exception:pass

def main():
    required=('SFTP_HOST','SFTP_USERNAME','SFTP_PRIVATE_KEY_B64','SFTP_ROOT')
    for name in required:
        if not os.environ.get(name):raise RuntimeError('Bodgybros SFTP variable missing: '+name)
    root=posixpath.normpath(os.environ['SFTP_ROOT'].replace('\\','/').strip())
    if root.endswith('/sps/spr/d') or root.endswith('/sps/spr/g'):
        root=posixpath.dirname(posixpath.dirname(posixpath.dirname(root)))
    elif root.endswith('/sps/spr'):root=posixpath.dirname(root)
    elif root.endswith('/public_html'):root=posixpath.join(root,'sps')
    if not root.endswith('/sps'):raise RuntimeError('Bodgybros website /sps root not identified')
    pem=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=typ.from_private_key(io.StringIO(pem));break
        except Exception:pass
    if key is None:raise RuntimeError('Cannot load Bodgybros SFTP key')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=os.environ['SFTP_HOST'],port=int(os.environ.get('SFTP_PORT') or 22),
           username=os.environ['SFTP_USERNAME'],pkey=key,
           timeout=10,auth_timeout=12,banner_timeout=12,
           allow_agent=False,look_for_keys=False)
        with ssh.open_sftp() as sftp:
            js_path=posixpath.join(root,'script.js')
            existing=read(sftp,js_path)
            js=existing.decode('utf-8')
            php_path=posixpath.join(root,'spr-shift-cache.php')
            try:old_php=read(sftp,php_path)
            except FileNotFoundError:old_php=None
            php=urllib.request.urlopen(PHP_URL,timeout=12).read()
            if not php.startswith(b'<?php') or b'read-only' not in php.lower():
                raise RuntimeError('Read-only PHP manifest reader source unexpected')
            if old_php is not None and old_php!=php and b'Build 681:' not in old_php:
                raise RuntimeError('Existing unrecognised spr-shift-cache.php; refusing overwrite')
            if MARK in js:
                print('[681 WEBSITE] Frontend prepared manifest reader already installed',flush=True)
                return
            needle="const url='./spr/x/'+role+'/'+date+'/manifest.json';"
            replacement="const url='./spr-shift-cache.php?role='+encodeURIComponent(role)+'&date='+encodeURIComponent(date);"
            if js.count(needle)!=1:
                raise RuntimeError('Expected Build 680 static manifest lookup not present')
            js=js.replace(needle,replacement,1)
            sha_needle="const sha=String(state.sourceSha||'').toLowerCase();"
            sha_replacement="const sha=String(state.sourceSha||await publishedIndexSha(date,state.role)).toLowerCase();"
            if js.count(sha_needle)!=1:raise RuntimeError('Expected cached index source SHA reader not found')
            js=js.replace(sha_needle,sha_replacement,1)
            js=MARK+'\n'+js
            html_changes=[]
            for name in ('index.php','index.html'):
                path=posixpath.join(root,name)
                raw=read(sftp,path)
                html=raw.decode('utf-8')
                if html.count('./script.js?v=680')!=1:
                    raise RuntimeError('Expected Build 680 HTML version missing in '+name)
                html=html.replace('./script.js?v=680','./script.js?v=681',1)
                html=re.sub(r'(class=["\']build-number["\']>Build )680\b',r'\g<1>681',html,count=1)
                html_changes.append((path,raw,html.encode('utf-8')))
            backups=Path('/data/website-build681-backups')
            backups.mkdir(parents=True,exist_ok=True)
            for path,payload in [(js_path,existing)]+[(path,raw) for path,raw,new in html_changes]:
                (backups/posixpath.basename(path)).write_bytes(payload)
            # PHP endpoint first, then JS, then HTML cache keys.
            atomic(sftp,php_path,old_php,php)
            print('[681 VERIFIED] Read-only spr-shift-cache.php published; SHA '+sha(php)[:12],flush=True)
            atomic(sftp,js_path,existing,js.encode('utf-8'))
            print('[681 VERIFIED] script.js prepared shift manifest URL updated; SHA '+sha(js.encode())[:12],flush=True)
            for path,old,new in html_changes:
                atomic(sftp,path,old,new)
                print('[681 VERIFIED] '+posixpath.basename(path)+' cache-busting Build 681',flush=True)
    finally:ssh.close()
    try:
        response=requests.get('https://www.bodgybros.com/sps/spr-shift-cache.php',
            params={'date':'2026-10-26','role':'d'},timeout=(8,20),allow_redirects=False)
        print('[681 PUBLIC TEST] PHP shift cache HTTP '+str(response.status_code)+
              ' response_type='+str(response.headers.get('Content-Type',''))[:45],flush=True)
        if response.ok:
            obj=response.json()
            print('[681 PUBLIC TEST] Shift 65 prepared='+str('65' in obj.get('shifts',[]))+
                  ', indexed SHA exists='+str(bool(obj.get('sourceSha'))),flush=True)
    except Exception as exc:print('[681 PUBLIC TEST] Unavailable: '+str(exc)[:160],flush=True)
if __name__=='__main__':main()
