#!/usr/bin/env python3
"""Read-only diagnosis of Bodgybros Build 680 prepared shift 65.
Print presence, hash comparison, and public HTTP statuses; never print secrets.
"""
import os,base64,io,posixpath,json
import paramiko,requests
from pathlib import Path
def main():
    env=os.environ
    raw=base64.b64decode(env['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(raw));break
        except Exception:pass
    if key is None:raise RuntimeError('Cannot parse primary key')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=env['SFTP_HOST'],port=int(env.get('SFTP_PORT') or 22),
                    username=env['SFTP_USERNAME'],pkey=key,
                    timeout=10,auth_timeout=10,banner_timeout=10,
                    allow_agent=False,look_for_keys=False)
        with ssh.open_sftp() as sftp:
            r=posixpath.normpath(env['SFTP_ROOT'].strip())
            if r.endswith('/spr/d') or r.endswith('/spr/g'):base=posixpath.dirname(posixpath.dirname(r))
            elif r.endswith('/spr'):base=posixpath.dirname(r)
            elif r.endswith('/public_html'):base=r+'/sps'
            elif r.endswith('/sps'):base=r
            else:raise RuntimeError('Unknown website SFTP_ROOT')
            print('[681 DIAG] SFTP website /sps base verified, no secrets printed',flush=True)
            date='2026-10-26'
            mpath=base+'/spr/x/d/'+date+'/manifest.json'
            pdf=base+'/spr/x/d/'+date+'/65.pdf'
            index=base+'/spr/i/d/'+date+'.meta.json'
            try:
                with sftp.open(mpath,'rb') as f:m=json.loads(f.read(300000))
                print('[681 DIAG] Cache manifest date=%s role=%s version=%s count=%s complete=%s has65=%s source_sha_tail=%s' % (
                    m.get('date'),m.get('role'),m.get('version'),m.get('count'),m.get('complete'),'65' in m.get('shifts',[]),str(m.get('sourceSha',''))[-10:]),flush=True)
            except Exception as err:print('[681 DIAG] SFTP manifest missing/read error: '+str(err)[:160],flush=True);m={}
            try:
                st=sftp.stat(pdf)
                with sftp.open(pdf,'rb') as f:head=f.read(7)
                print('[681 DIAG] Prepared Shift 65 SFTP bytes=%s pdf_header=%s' % (st.st_size,head.startswith(b'%PDF-')),flush=True)
            except Exception as err:print('[681 DIAG] Prepared Shift 65 SFTP missing/read error: '+str(err)[:160],flush=True)
            try:
                with sftp.open(index,'rb') as f:metadata=json.loads(f.read(50000))
                print('[681 DIAG] Index source hash matches manifest=%s parser=%s' % (
                    str(metadata.get('sourceSha','')).lower()==str(m.get('sourceSha','')).lower(),
                    metadata.get('parserBuild')),flush=True)
            except Exception as err:print('[681 DIAG] Index meta read error: '+str(err)[:160],flush=True)
            with sftp.open(base+'/script.js','rb') as f:script=f.read().decode('utf-8')
            print('[681 DIAG] Site JS has Build680=%s; state.sourceSha is assigned=%s; manifest fetch helper=%s' % (
                'SPR_PREEXTRACTED_ORIGINAL_SHIFT_PDF_680' in script,
                'state.sourceSha=cached.sourceSha' in script,
                'async function getPreparedShiftManifest()' in script),flush=True)
    finally:ssh.close()
    for filename in ('spr/x/d/2026-10-26/manifest.json','spr/x/d/2026-10-26/65.pdf',
                     'spr/i/d/2026-10-26.meta.json'):
        url='https://www.bodgybros.com/sps/'+filename
        try:
            response=requests.get(url,timeout=(6,15),allow_redirects=False,stream=True,
                                  headers={'User-Agent':'Mozilla/5.0'})
            print('[681 DIAG] Public GET %s HTTP=%s content_type=%s length=%s' %
                (filename,response.status_code,response.headers.get('Content-Type'),
                 response.headers.get('Content-Length')),flush=True)
            if filename.endswith('manifest.json') and response.ok:
                data=response.json()
                print('[681 DIAG] Public manifest has65=%s count=%s sha_tail=%s' % (
                    '65' in data.get('shifts',[]),data.get('count'),str(data.get('sourceSha',''))[-10:]),flush=True)
            response.close()
        except Exception as exc:print('[681 DIAG] GET %s error=%s' % (filename,str(exc)[:140]),flush=True)
if __name__=='__main__':main()
