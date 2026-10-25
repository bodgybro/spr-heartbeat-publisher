#!/usr/bin/env python3
"""Build 682: eliminate public .json/.php cache metadata lookup entirely.

SFTP-copy already prepared Shift 65 to a source-SHA-qualified PDF filename
and patch only the frontend's prepared-PDF resolver. The browser downloads
the small original text-preserving PDF directly, without rendering pages or
parsing the full SPR. Future shifts are published to SHA-qualified paths by
Railway Build 682.
"""
import base64,hashlib,io,json,os,posixpath,re,urllib.request
from pathlib import Path
import paramiko,requests

MARK='// SPR_SHA_NAMED_ORIGINAL_SHIFT_PDF_682'
OLD=r'''async function getPreparedShiftPdf(shift){
  const manifest=await getPreparedShiftManifest();
  if(!manifest||!manifest.shifts.includes(shift))return '';
  return './spr/x/'+manifest.role+'/'+manifest.date+'/'+encodeURIComponent(shift)+'.pdf';
}'''
NEW=r'''async function getPreparedShiftPdf(shift){
  const cached=state.shiftPdfUrls.get(shift);
  if(cached)return cached;
  const date=String(state.loadedDate||'');
  const role=state.role==='guard'?'g':'d';
  let sha=String(state.sourceSha||'').toLowerCase();
  if(!/^[a-f0-9]{64}$/.test(sha)){
    sha=String(await publishedIndexSha(date,state.role)||'').toLowerCase();
    if(/^[a-f0-9]{64}$/.test(sha))state.sourceSha=sha;
  }
  if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||!/^[a-f0-9]{64}$/.test(sha)){
    console.info('No source checksum for cached Shift '+shift+'; using original-PDF fallback');
    return '';
  }
  const url='./spr/x/'+role+'/'+date+'/'+encodeURIComponent(shift)+'-'+sha+'.pdf';
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),12000);
  try{
    // The filename encodes the entire source PDF's SHA-256, so an old
    // extracted shift can never accidentally match the selected index.
    // This fetch is a small PDF, not the full SPR; keep its selectable text.
    const result=await fetch(url,{credentials:'same-origin',cache:'force-cache',
      signal:controller.signal});
    if(!result.ok){
      console.info('Prepared original Shift '+shift+' HTTP '+result.status+'; fallback to source');
      return '';
    }
    const bytes=await result.arrayBuffer();
    const prefix=new TextDecoder('ascii').decode(bytes.slice(0,5));
    if(prefix!=='%PDF-')throw new Error('Prepared shift is not a real PDF');
    const blob=URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));
    state.shiftPdfUrls.set(shift,blob);
    return blob;
  }catch(error){
    console.info('Prepared original Shift '+shift+' unavailable; source fallback',error);
    return '';
  }finally{clearTimeout(timer)}
}'''

def sha(data):return hashlib.sha256(data).hexdigest()
def read(sftp,path):
    with sftp.open(path,'rb') as f:return f.read()
def put(sftp,path,old,new):
    if old is not None and sha(read(sftp,path))!=sha(old):
        raise RuntimeError('Concurrent website change: '+posixpath.basename(path))
    tmp=path+'.build682-pending'
    try:
        with sftp.open(tmp,'wb') as f:f.write(new)
        if sha(read(sftp,tmp))!=sha(new):raise RuntimeError('SFTP staged file SHA-256 mismatch')
        sftp.posix_rename(tmp,path)
        if sha(read(sftp,path))!=sha(new):raise RuntimeError('SFTP final file SHA-256 mismatch')
    finally:
        try:sftp.remove(tmp)
        except Exception:pass

def main():
    for env in ('SFTP_HOST','SFTP_USERNAME','SFTP_PRIVATE_KEY_B64','SFTP_ROOT'):
        if not os.environ.get(env):raise RuntimeError('Primary Bodgybros SFTP env missing: '+env)
    root=posixpath.normpath(os.environ['SFTP_ROOT'].replace('\\','/'))
    if root.endswith('/sps/spr/d') or root.endswith('/sps/spr/g'):
        root=posixpath.dirname(posixpath.dirname(posixpath.dirname(root)))
    elif root.endswith('/sps/spr'):root=posixpath.dirname(root)
    elif root.endswith('/public_html'):root=posixpath.join(root,'sps')
    if not root.endswith('/sps'):raise RuntimeError('Bodgybros /sps root not identified')
    key_data=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(key_data));break
        except Exception:pass
    if key is None:raise RuntimeError('Could not parse Bodgybros SFTP key')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=os.environ['SFTP_HOST'],port=int(os.environ.get('SFTP_PORT') or 22),
            username=os.environ['SFTP_USERNAME'],pkey=key,
            timeout=12,auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
        with ssh.open_sftp() as sftp:
            js_path=posixpath.join(root,'script.js')
            original=read(sftp,js_path)
            js=original.decode('utf-8')
            if MARK in js:
                print('[682 WEBSITE] Already using SHA-named shift PDFs',flush=True)
                return
            if js.count(OLD)!=1 or 'SPR_PREEXTRACTED_ORIGINAL_SHIFT_PDF_680' not in js:
                raise RuntimeError('Expected current prepared-PDF resolver differs; site untouched')
            new=MARK+'\n'+js.replace(OLD,NEW,1)
            other=[]
            for name in ('index.php','index.html'):
                path=posixpath.join(root,name)
                old=read(sftp,path)
                html=old.decode('utf-8')
                if html.count('./script.js?v=681')!=1:
                    raise RuntimeError('Build 681 cache-busting key not found in '+name)
                html=html.replace('./script.js?v=681','./script.js?v=682',1)
                html=re.sub(r'(class=["\']build-number["\']>Build )681\b',r'\g<1>682',html,count=1)
                other.append((path,old,html.encode('utf-8')))
            # Verify the existing ready file belongs to the current, published
            # 26-Oct index and make its new SHA-specific name before JS changes.
            folder=posixpath.join(root,'spr/x/d/2026-10-26')
            manifest=json.loads(read(sftp,posixpath.join(folder,'manifest.json')))
            meta=json.loads(read(sftp,posixpath.join(root,'spr/i/d/2026-10-26.meta.json')))
            digest=str(meta.get('sourceSha') or '').lower()
            if (manifest.get('sourceSha','').lower()!=digest or
                not re.fullmatch('[a-f0-9]{64}',digest) or
                '65' not in manifest.get('shifts',[])):
                raise RuntimeError('26 October indexed Shift 65 cache does not match current source')
            prepared=read(sftp,posixpath.join(folder,'65.pdf'))
            if not prepared.startswith(b'%PDF-'):raise RuntimeError('Shift 65 source is not a valid PDF')
            new_name=posixpath.join(folder,'65-'+digest+'.pdf')
            try:prior=read(sftp,new_name)
            except FileNotFoundError:prior=None
            if prior!=prepared:put(sftp,new_name,prior,prepared)
            print('[682 VERIFIED] 26-Oct Shift 65 source-SHA PDF uploaded, '+str(len(prepared))+' bytes',flush=True)
            backups=Path('/data/website-build682-backups')
            backups.mkdir(parents=True,exist_ok=True)
            (backups/'script.js').write_bytes(original)
            for path,old,_ in other:(backups/posixpath.basename(path)).write_bytes(old)
            put(sftp,js_path,original,new.encode('utf-8'))
            print('[682 VERIFIED] script.js now opens original source-SHA PDF directly, no manifest',flush=True)
            for path,old,updated in other:
                put(sftp,path,old,updated)
                print('[682 VERIFIED] '+posixpath.basename(path)+' references Build 682',flush=True)
    finally:ssh.close()
    try:
        url='https://www.bodgybros.com/sps/spr/x/d/2026-10-26/65-'+digest+'.pdf'
        r=requests.get(url,timeout=(8,22),stream=True,allow_redirects=False)
        print('[682 PUBLIC TEST] Source-hash Shift 65 PDF HTTP '+str(r.status_code)+
            ' content-type='+str(r.headers.get('Content-Type',''))[:30],flush=True)
        r.close()
    except Exception as e:print('[682 PUBLIC TEST] '+str(e)[:140],flush=True)
if __name__=='__main__':main()
