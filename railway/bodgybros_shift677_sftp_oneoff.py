#!/usr/bin/env python3
"""Build 677: patch only Bodgybros SPR shift opening code via existing SFTP.
Guard every changed JS block; never overwrite an unexpected website build.
Use the prepared index page mapping and selected-page PDF.js rendering.
"""
import os,base64,io,posixpath,hashlib,re
from pathlib import Path
import paramiko

def once(text,old,new,label):
    n=text.count(old)
    if n!=1:raise RuntimeError(f"Shift JS anchor {label} differs; found {n}, site left untouched")
    return text.replace(old,new,1)

def patch_script(text):
    if '// SPR_BODGYBROS_INDEXED_SHIFT_677' in text:
        return text,False
    s=text
    s=once(s,"if(isKustomSprHost()&&!window.__SPR_PREINDEX_MODE)return;",
       "if(!window.__SPR_PREINDEX_MODE)return;",'full-PDF prefetch')
    s=once(s,"    if(isKustomSprHost())warmSecondaryShiftSource();\n    else scheduleVisibleShiftPdfPrewarm();",
       "    // Build 677: do not prewarm whole PDF before first shift click.",'prewarm schedule')
    s=once(s,
       "    const task=state.pdfBytes\n      ? pdfjsLib.getDocument({data:new Uint8Array(state.pdfBytes.slice(0))})\n      : pdfjsLib.getDocument({url:new URL(state.sourceUrl,document.baseURI).href,\n          rangeChunkSize:262144,disableStream:true,disableAutoFetch:true,\n          withCredentials:false});",
       "    // Prefer selective HTTP Range requests over parsing the complete PDF.\n    const online=state.sourceUrl&&!state.sourceUrl.startsWith('blob:');\n    const task=online\n      ? pdfjsLib.getDocument({url:new URL(state.sourceUrl,document.baseURI).href,\n          rangeChunkSize:262144,disableStream:true,disableAutoFetch:true,\n          withCredentials:false})\n      : pdfjsLib.getDocument({data:new Uint8Array(state.pdfBytes.slice(0))});",
       'pdfjs range source')
    s=once(s,
       "    if(isKustomSprHost()&&state.sourceUrl){\n      // Kustom: fetch/render only Shift pages; the large source is not parsed\n      // with pdf-lib on the critical first-click path.",
       "    if(state.sourceUrl||state.pdfDoc){\n      // Use indexed source-page numbers on Bodgybros and render only Shift pages.",
       'primary indexed reader')
    s=once(s,"function scheduleVisibleShiftPdfPrewarm(){",
       "function scheduleVisibleShiftPdfPrewarm(){\n  // Build 677: avoid prewarm starving first requested shift.\n  return;",
       'prewarm function')
    s=once(s,
       "    const url=await prepareShiftPdfUrl(shift,stage=>{\n      if(!viewer.closed)viewer.document.body.textContent=stage;\n    });",
       "    let shiftTimeout;\n    const url=await Promise.race([\n      prepareShiftPdfUrl(shift,stage=>{\n        if(!viewer.closed)viewer.document.body.textContent=stage;\n      }),\n      new Promise((_,reject)=>{shiftTimeout=setTimeout(()=>reject(new Error('Shift page extraction exceeded 45 seconds')),45000)})\n    ]).finally(()=>clearTimeout(shiftTimeout));",
       'absolute timeout')
    s=once(s,"    if(isKustomSprHost()&&state.sourceUrl){\n      const fallback=viewer.document.createElement('a');",
       "    if(state.sourceUrl){\n      const fallback=viewer.document.createElement('a');",
       'backup original PDF link')
    return '// SPR_BODGYBROS_INDEXED_SHIFT_677\n'+s,True

def sps_path(root):
    root=posixpath.normpath(root.replace('\\','/'))
    if root.endswith('/sps'):return root
    if root.endswith('/sps/spr'):return posixpath.dirname(root)
    if root.endswith('/sps/spr/d') or root.endswith('/sps/spr/g'):
        return posixpath.dirname(posixpath.dirname(posixpath.dirname(root)))
    if root.endswith('/public_html'):return posixpath.join(root,'sps')
    raise RuntimeError('SFTP_ROOT does not identify a known Bodgybros /sps layout')

def sha(data):return hashlib.sha256(data).hexdigest()
def read(sftp,path):
    with sftp.open(path,'rb') as f:return f.read()
def atomic_write(sftp,path,payload,old_sha):
    if sha(read(sftp,path))!=old_sha:
        raise RuntimeError('Concurrent website edit detected: '+posixpath.basename(path))
    temp=path+'.build677-updating'
    try:
        with sftp.open(temp,'wb') as f:f.write(payload)
        if sha(read(sftp,temp))!=sha(payload):
            raise RuntimeError('SFTP checksum mismatch')
        sftp.posix_rename(temp,path)
        if sha(read(sftp,path))!=sha(payload):
            raise RuntimeError('Remote final checksum mismatch')
    finally:
        try:sftp.remove(temp)
        except Exception:pass

def main():
    required=('SFTP_HOST','SFTP_USERNAME','SFTP_PRIVATE_KEY_B64','SFTP_ROOT')
    if not all(os.getenv(k) for k in required):
        raise RuntimeError('Bodgybros SFTP missing, leaving site unchanged')
    host=os.environ['SFTP_HOST'].strip()
    user=os.environ['SFTP_USERNAME'].strip()
    port=int(os.getenv('SFTP_PORT') or 22)
    root=sps_path(os.environ['SFTP_ROOT'])
    private=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=typ.from_private_key(io.StringIO(private));break
        except Exception:pass
    if key is None:raise RuntimeError('Bodgybros SFTP key invalid')
    hosts=Path('/data/credentials/spr-sftp-known_hosts')
    if not hosts.exists():raise RuntimeError('Previously accepted primary SFTP host key missing; not deploying website patch')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(hosts))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=host,port=port,username=user,pkey=key,
           timeout=10,auth_timeout=12,banner_timeout=12,
           allow_agent=False,look_for_keys=False)
        with ssh.open_sftp() as sftp:
            js_path=posixpath.join(root,'script.js')
            current=read(sftp,js_path)
            updated,changed=patch_script(current.decode('utf-8'))
            if not changed:
                print('[BUILD 677 WEBSITE] Already installed; no remote edits',flush=True)
                return
            # Preserve the exact existing Bodgybros HTML/PHP, merely bump
            # the JS cache-key. Never replace these pages with Kustom HTML.
            changes=[(js_path,current,updated.encode('utf-8'))]
            for name in ('index.php','index.html'):
                path=posixpath.join(root,name)
                data=read(sftp,path)
                doc=data.decode('utf-8')
                updated_doc,count=re.subn(r'(\./script\.js\?v=)\d+',r'\g<1>677',doc,count=1)
                if count!=1:raise RuntimeError(name+' script version anchor missing; no site changes made')
                updated_doc=re.sub(r'(class=["\']build-number["\']>Build )\d+',r'\g<1>677',updated_doc,count=1)
                changes.append((path,data,updated_doc.encode('utf-8')))
            backups=Path('/data/website-build677-backups')
            backups.mkdir(parents=True,exist_ok=True)
            for path,data,_ in changes:
                save=backups/posixpath.basename(path)
                if not save.exists():save.write_bytes(data)
            # SFTP change order: JS then PHP and HTML. Never touch PDFs or indexes.
            for path,old,new in changes:
                atomic_write(sftp,path,new,sha(old))
                print('[BUILD 677 WEBSITE PATCHED] '+posixpath.basename(path)+
                    ' SHA-256 '+sha(new)[:12],flush=True)
    finally:ssh.close()

if __name__=='__main__':main()
