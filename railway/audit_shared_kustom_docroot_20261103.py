#!/usr/bin/env python3
"""READ-ONLY audit: same cPanel login vs shared vhost/docroot for Kustom.

No writes or site changes. Never log credentials, SSH username or secret values.
"""
import os,io,base64,posixpath,stat,urllib.parse,json
import requests,paramiko

E=os.environ
def yn(x):return 'yes' if x else 'no'
def filtered_path(p):
    # Don't disclose hosting username / account home path in logs.
    p=str(p or '').replace('\\','/').rstrip('/')
    keep=[]
    for seg in p.split('/'):
        if not seg:continue
        low=seg.lower()
        keep.append(seg if ('kustomvinyl' in low or low in ('public_html','sps','www','htdocs','domains','sites')) else '…')
    return '/'.join(keep)[-210:]

def domains_from_payload(data):
    arr=[]
    if isinstance(data,dict):
        for k in ('main_domain','addon_domains','parked_domains','sub_domains','domain'):
            v=data.get(k)
            if isinstance(v,str):arr.append(v)
            if isinstance(v,list):
                for x in v:
                    if isinstance(x,str):arr.append(x)
                    if isinstance(x,dict):
                        for field in ('domain','domain_name','name'):
                            if x.get(field):arr.append(str(x[field]));break
            if isinstance(v,dict):
                for x in v.values():
                    if isinstance(x,dict):arr.append(str(x.get('domain') or x.get('domain_name') or ''))
                    elif isinstance(x,str):arr.append(x)
    elif isinstance(data,list):
        for x in data:
            if isinstance(x,dict):arr.append(str(x.get('domain') or x.get('domain_name') or ''))
    return sorted(set(d for d in arr if d and d!='None'))

print('[KUSTOM SAME-ACCOUNT AUDIT] Begin read-only',flush=True)

if all(E.get(k) for k in ('CPANEL_HOST','CPANEL_USERNAME','CPANEL_API_TOKEN')):
    raw=E['CPANEL_HOST'].strip()
    host=urllib.parse.urlparse(raw if '://' in raw else 'https://'+raw).hostname
    port=int(E.get('CPANEL_PORT') or 2083)
    verify=E.get('CPANEL_VERIFY_SSL','1').strip().lower() not in ('false','no','0')
    for func in ('list_domains','domains_data'):
        try:
            response=requests.get(
                f'https://{host}:{port}/execute/DomainInfo/{func}',
                headers={'Authorization':f'cpanel {E["CPANEL_USERNAME"]}:{E["CPANEL_API_TOKEN"]}'},
                params={'format':'hash'} if func=='domains_data' else None,
                timeout=18,verify=verify
            )
            data=response.json() if response.ok else {}
            domains=domains_from_payload(data.get('data',{}))
            print('[KUSTOM SAME-ACCOUNT AUDIT] cPanel',func,'HTTP',response.status_code,'UAPI status',data.get('status'),
                  'domainCount',len(domains),'kustomlisted',yn(any('kustomvinyls.com' in d.lower() for d in domains)),flush=True)
            print('[KUSTOM SAME-ACCOUNT AUDIT] Domains:',','.join(domains[:25]),flush=True)
            for k in ('main_domain','addon_domains','parked_domains','sub_domains'):
                entries=(data.get('data') or {}).get(k) if isinstance(data.get('data'),dict) else None
                if entries:
                    values=entries if isinstance(entries,list) else [entries]
                    for item in values:
                        if not isinstance(item,dict):continue
                        dom=str(item.get('domain') or item.get('domain_name') or '')
                        if 'kustomvinyl' in dom.lower():
                            print('[KUSTOM SAME-ACCOUNT AUDIT] Kustom reported docroot:',filtered_path(item.get('documentroot') or item.get('document_root') or item.get('docroot')),flush=True)
        except Exception as ex:
            print('[KUSTOM SAME-ACCOUNT AUDIT] cPanel',func,'error',type(ex).__name__,str(ex)[:100],flush=True)
else:print('[KUSTOM SAME-ACCOUNT AUDIT] cPanel credentials unavailable',flush=True)

key_blob=base64.b64decode(E['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
key=None
for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=cls.from_private_key(io.StringIO(key_blob));break
    except Exception:pass
if not key:raise RuntimeError('Primary account SFTP key not usable')
ssh=paramiko.SSHClient()
ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(hostname=E['SFTP_HOST'],username=E['SFTP_USERNAME'],
            port=int(E.get('SFTP_PORT') or 22),pkey=key,timeout=12,
            banner_timeout=12,auth_timeout=12,
            allow_agent=False,look_for_keys=False)
try:
    with ssh.open_sftp() as ftp:
        root=E['SFTP_ROOT'].replace('\\','/').rstrip('/')
        if root.endswith('/sps/spr'):root=root[:-4]
        elif root.endswith('/public_html'):root+='/sps'
        if not root.endswith('/sps'):raise RuntimeError('Existing SFTP root not /sps')
        candidates=['.', '/', '/home', '/home/'+E.get('SFTP_USERNAME',''),root,posixpath.dirname(root),
                    posixpath.dirname(posixpath.dirname(root)),E.get('CPANEL_HOME','')]
        unique=set()
        for dirname in candidates:
            if not dirname or dirname in unique:continue
            unique.add(dirname)
            try:
                entries=ftp.listdir_attr(dirname)
                dirs=[x.filename for x in entries if stat.S_ISDIR(x.st_mode)]
                relevant=[d for d in dirs if ('kustom' in d.lower() or
                       d.lower() in ('public_html','www','domains','sites','htdocs','sps','www.kustomvinyls.com'))]
                print('[KUSTOM SAME-ACCOUNT AUDIT] SFTP directory',filtered_path(dirname),
                      'readable yes','folders',len(dirs),'relevant',','.join(relevant[:35]),flush=True)
                if len(dirs)<22: print('[KUSTOM SAME-ACCOUNT AUDIT] folders:',','.join(dirs[:22]),flush=True)
            except Exception as ex:
                print('[KUSTOM SAME-ACCOUNT AUDIT] SFTP directory',filtered_path(dirname),'readable no',type(ex).__name__,flush=True)
        test_paths=[]
        rootparent=posixpath.dirname(posixpath.dirname(root))
        for parent in (rootparent,posixpath.dirname(rootparent),posixpath.dirname(root),'/home/'+E.get('SFTP_USERNAME','')):
            for name in ('kustomvinyls.com','kustomvinyls','public_html/kustomvinyls.com','domains/kustomvinyls.com/public_html'):
                test_paths.append(posixpath.join(parent,name))
        dest=set()
        for p in test_paths:
            if p in dest:continue
            dest.add(p)
            try:
                st=ftp.stat(p)
                if stat.S_ISDIR(st.st_mode):
                    print('[KUSTOM SAME-ACCOUNT AUDIT] candidate destination exists',filtered_path(p),
                          'entries',len(ftp.listdir_attr(p)),flush=True)
            except (OSError,IOError):pass
finally:ssh.close()
print('[KUSTOM SAME-ACCOUNT AUDIT] Done',flush=True)
