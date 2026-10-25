#!/usr/bin/env python3
"""Build 680: prepare original, selectable shift PDFs at SPR pre-index time.

Read the same SHA-matched PDF and prepared shift-page mapping over existing
Bodgybros SFTP. Copy source pages via PyMuPDF, never render screenshots.
Publish independent /spr/x/{d|g}/{date}/{shift}.pdf files, and write a
SHA-bound manifest only after ALL expected files have been verified.
Backfill today's and tomorrow's indexed PDFs in background on startup.
All failures are isolated from required PDF, index and roster uploads.
"""
from pathlib import Path
import ast,sys
MARKER='# SPR_SHIFT_PDF_PREEXTRACT_680'
EXTENSION=r'''
# SPR_SHIFT_PDF_PREEXTRACT_680
import datetime as _x_datetime
from zoneinfo import ZoneInfo as _x_ZoneInfo
import gzip as _x_gzip
import posixpath as _x_path
import hashlib as _x_hash
import io as _x_io
import base64 as _x_base64

_X_SHIFT_LOCK=threading.Lock()
_X_SHIFT_QUEUE_LOCK=threading.Lock()
_X_SHIFT_QUEUE=[]
_X_SHIFT_STARTED=False

def _x_shift_pages(index):
    """Same first-occurrence Shift x 1-of-N chain as frontend Build 505."""
    found={};occur={}
    match_expression=re.compile(r'\bShift\s+((?:EXD|DEX|EXG|GEX|SBTD|SBGT)\d{1,3}|\d{1,4})\s+(\d+)\s+of\s+(\d+)\b',re.I)
    for page in index.get('pages') or []:
        if not isinstance(page,dict):continue
        text=str(page.get('text') or '')
        matched=match_expression.search(text)
        if not matched:continue
        shift=matched[1].upper()
        part,total=int(matched[2]),max(1,int(matched[3]))
        page_no=int(page.get('pageNo') or 0)
        if page_no<1:continue
        state=occur.setdefault(shift,{'started':False,'complete':False,'last':0})
        keep=False
        if not state['started'] and part==1:
            state.update(started=True,last=1,complete=(total==1));keep=True
        elif state['started'] and not state['complete'] and part==state['last']+1:
            state.update(last=part,complete=(part>=total));keep=True
        if keep:found.setdefault(shift,[]).append(page_no)
    return found

@__import__('contextlib').contextmanager
def _x_shift_sftp():
    import paramiko
    env=os.environ
    host=env.get('SFTP_HOST','').strip()
    user=env.get('SFTP_USERNAME','').strip()
    raw=env.get('SFTP_PRIVATE_KEY_B64','').strip()
    root=env.get('SFTP_ROOT','').strip()
    if not all((host,user,raw,root)):
        raise RuntimeError('Bodgybros SFTP configuration incomplete')
    key_string=_x_base64.b64decode(raw).decode('utf-8')
    key=None
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=typ.from_private_key(_x_io.StringIO(key_string));break
        except Exception:pass
    if key is None:raise RuntimeError('Could not parse SFTP key for shift pre-extraction')
    known=DATA_ROOT/'credentials'/'spr-sftp-known_hosts'
    if not known.exists():raise RuntimeError('Primary SFTP known-hosts verification absent')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(known))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    conn=None
    try:
        ssh.connect(hostname=host,port=int(env.get('SFTP_PORT') or 22),
          username=user,pkey=key,timeout=12,auth_timeout=12,banner_timeout=12,
          look_for_keys=False,allow_agent=False)
        conn=ssh.open_sftp()
        conn.get_channel().settimeout(90)
        pdf_dir=_spr_remote_subdir(root,'drivers')
        spr_base=_x_path.dirname(pdf_dir)
        yield conn,spr_base
    finally:
        try:
            if conn is not None:conn.close()
        finally:ssh.close()

def _x_read_remote(sftp,remote):
    size=sftp.stat(remote).st_size
    if size>262144:
        print(f'  [SHIFT SFTP READING] {_x_path.basename(remote)}: {size} bytes (prefetched)',flush=True)
    with sftp.open(remote,'rb') as stream:
        if size>262144:
            stream.prefetch(file_size=size,max_concurrent_requests=16)
        payload=stream.read()
    if len(payload)!=size:
        raise RuntimeError('Shift input file size changed while downloading')
    return payload

def _x_mkdir(sftp,root,role,date):
    for part in ('x','x/'+role,'x/'+role+'/'+date):
        folder=_x_path.join(root,part)
        try:sftp.stat(folder)
        except FileNotFoundError:sftp.mkdir(folder)

def _x_write_verified(sftp,target,payload):
    expected=_x_hash.sha256(payload).hexdigest()
    tmp=target+'.shift680-'+str(os.getpid())
    try:
        with sftp.open(tmp,'wb') as out:out.write(payload)
        if sftp.stat(tmp).st_size!=len(payload):
            raise RuntimeError('SFTP extracted shift size mismatch')
        check=_x_hash.sha256()
        with sftp.open(tmp,'rb') as reader:
            while True:
                chunk=reader.read(262144)
                if not chunk:break
                check.update(chunk)
        if check.hexdigest()!=expected:
            raise RuntimeError('SFTP extracted shift SHA-256 mismatch')
        sftp.posix_rename(tmp,target)
    finally:
        try:sftp.remove(tmp)
        except Exception:pass

def _x_shift_job(date,role):
    import fitz
    print(f'  [SHIFT CACHE START] {date} {role}',flush=True)
    if not re.fullmatch(r'\d{4}-\d\d-\d\d',date) or role not in ('d','g'):
        raise RuntimeError('Invalid SPR shift extraction target')
    with _X_SHIFT_LOCK:
        with _x_shift_sftp() as (sftp,spr):
            prefix='All Drivers Combined ' if role=='d' else 'All Guards Combined '
            filename=prefix+date[8:10]+'_'+date[5:7]+'_'+date[0:4]+'.pdf'
            pdf_path=_x_path.join(spr,role,filename)
            index_path=_x_path.join(spr,'i',role,date+'.json.gz')
            index_meta_path=_x_path.join(spr,'i',role,date+'.meta.json')
            try:
                meta=json.loads(_x_read_remote(sftp,index_meta_path).decode('utf-8'))
                compressed=_x_read_remote(sftp,index_path)
            except FileNotFoundError:
                print(f'  [SHIFT INDEX NOT READY] {date} {role}',flush=True)
                return False
            expected=meta.get('sourceSha') or ''
            if not re.fullmatch(r'[a-f0-9]{64}',expected,re.I):
                raise RuntimeError('Shift index source SHA missing')
            if len(compressed)!=meta.get('compressedBytes'):
                raise RuntimeError('Shift source index length differs from metadata')
            index=json.loads(_x_gzip.decompress(compressed))
            if index.get('sourceSha')!=expected or index.get('date')!=date:
                raise RuntimeError('Shift index source and date mismatch')
            if index.get('role')!=('driver' if role=='d' else 'guard'):
                raise RuntimeError('Shift index role mismatch')
            shift_map=_x_shift_pages(index)
            if not shift_map:raise RuntimeError('Prepared SPR contains no mapped shifts')
            out_dir=_x_path.join(spr,'x',role,date)
            manifest_path=_x_path.join(out_dir,'manifest.json')
            already_done=set()
            try:
                old=json.loads(_x_read_remote(sftp,manifest_path).decode('utf-8'))
                if old.get('sourceSha')==expected and old.get('version') in (680,682):
                    already_done=set(old.get('shifts') or []).intersection(shift_map)
                if (old.get('sourceSha')==expected and old.get('version')==682
                    and len(old.get('shifts') or [])==len(shift_map)
                    and set(old.get('shifts') or [])==set(shift_map)):
                    print(f'  [SHIFT PDF CACHE CURRENT] {date} {role}: {len(shift_map)} extracted PDFs',flush=True)
                    return True
            except FileNotFoundError:pass
            pdf_data=_x_read_remote(sftp,pdf_path)
            actual=_x_hash.sha256(pdf_data).hexdigest()
            if actual.lower()!=expected.lower():
                raise RuntimeError('Original SPR PDF differs from indexed SHA-256')
            pdf=fitz.open(stream=pdf_data,filetype='pdf')
            try:
                for pages in shift_map.values():
                    if any(p<1 or p>pdf.page_count for p in pages):
                        raise RuntimeError('An indexed shift page is outside its source PDF')
                _x_mkdir(sftp,spr,role,date)
                # Shift 65 first to immediately repair the reported reproduction;
                # every other shift is generated identically (not special-cased).
                priority=sorted(shift_map,key=lambda shift: (shift!='65',int(shift) if shift.isdigit() else 999999,shift))
                count=0
                for shift in priority:
                    pages=shift_map[shift]
                    target=_x_path.join(out_dir,shift+'.pdf')
                    hashed=_x_path.join(out_dir,shift+'-'+expected+'.pdf')
                    if shift in already_done:
                        try:
                            if sftp.stat(target).st_size>500:
                                try:
                                    sftp.stat(hashed)
                                except FileNotFoundError:
                                    _x_write_verified(sftp,hashed,_x_read_remote(sftp,target))
                                count+=1
                                if count==1 or count%30==0:
                                    print(f'  [SHIFT PDF CACHE RESUMED] {date} {role} {count}/{len(shift_map)}',flush=True)
                                continue
                        except FileNotFoundError:pass
                    extracted=fitz.open()
                    try:
                        for p in pages:
                            extracted.insert_pdf(pdf,from_page=p-1,to_page=p-1,
                                links=True,annots=True,widgets=True)
                        data=extracted.tobytes(garbage=3,deflate=True)
                    finally:extracted.close()
                    # Verify the exact selected page count before publication.
                    check=fitz.open(stream=data,filetype='pdf')
                    try:
                        if check.page_count!=len(pages):
                            raise RuntimeError('Shift extraction page-count mismatch')
                    finally:check.close()
                    # Hash-keyed PDFs are self-validating; no .json or PHP
                    # metadata HTTP request is needed for the Shift click.
                    _x_write_verified(sftp,hashed,data)
                    count+=1
                    if count==1 or count%30==0:
                        ready=priority[:count]
                        # Publish an SHA-bound PARTIAL manifest, so already
                        # prepared shifts open instantly while others extract.
                        partial=json.dumps({'version':682,'date':date,'role':role,
                            'sourceSha':expected,'shifts':ready,
                            'createdAt':int(time.time()),'count':count,
                            'complete':False},separators=(',',':')).encode('utf-8')
                        _x_write_verified(sftp,manifest_path,partial)
                        print(f'  [SHIFT PDFs PREPARED] {date} {role} {count}/{len(shift_map)}',flush=True)
                final=json.dumps({'version':682,'date':date,'role':role,
                    'sourceSha':expected,'shifts':sorted(shift_map),
                    'createdAt':int(time.time()),'count':len(shift_map),'complete':True},
                    separators=(',',':')).encode('utf-8')
                _x_write_verified(sftp,manifest_path,final)
                print(f'  [SHIFT PDF CACHE COMPLETE] {date} {role}: {count} original selectable shift PDFs',flush=True)
                return True
            finally:pdf.close()

def _x_shift_schedule(date,role):
    with _X_SHIFT_QUEUE_LOCK:
        if (date,role) not in _X_SHIFT_QUEUE:_X_SHIFT_QUEUE.append((date,role))

def _x_shift_worker():
    while True:
        with _X_SHIFT_QUEUE_LOCK:
            job=_X_SHIFT_QUEUE.pop(0) if _X_SHIFT_QUEUE else None
        if job is None:
            time.sleep(10)
            continue
        try:_x_shift_job(*job)
        except Exception as exc:
            print(f'  [SHIFT PDF PREP ERROR] {job[0]} {job[1]}: {str(exc)[:280]}',flush=True)

# Capture success of pre-indexing, but never block or change its result.
_X_ORIGINAL_PUBLISH_INDEX=_spr_publish_index
def _spr_publish_index(job,page,cfg):
    result=_X_ORIGINAL_PUBLISH_INDEX(job,page,cfg)
    _x_shift_schedule(job['date'],'d' if job['role']=='driver' else 'g')
    return result

def _x_shift_bootstrap():
    # Catch up the active range; pre-indexing and PDF uploads remain independent.
    current=_x_datetime.datetime.now(_x_ZoneInfo('Australia/Sydney')).date()
    for day in (current+_x_datetime.timedelta(days=1),current):
        for role in ('d','g'):
            _x_shift_schedule(day.strftime('%Y-%m-%d'),role)
    _x_shift_worker()

threading.Thread(target=_x_shift_bootstrap,name='spr-shift-pdf-preextract',
    daemon=True).start()
print('  [SHIFT ORIGINAL PDF CACHE READY] SFTP prepared PDFs, SHA-index-verified; single-site Bodgybros',flush=True)
'''
def apply(path):
    source=path.read_text(encoding='utf-8')
    if MARKER in source:
        print('Shift PDF pre-extract Build 680 already installed',flush=True)
        return
    tree=ast.parse(source)
    names={x.name for x in tree.body if isinstance(x,ast.FunctionDef)}
    for required in ('_spr_publish_index','_spr_publish_index_primary_sftp',
        '_spr_remote_subdir','run_update'):
        if required not in names:raise RuntimeError('Missing Bodgybros source function '+required)
    nodes=[x for x in tree.body if isinstance(x,ast.If) and
        '__name__' in (ast.get_source_segment(source,x.test) or '')]
    if not nodes:raise RuntimeError('Runtime entrypoint missing')
    first=min(x.lineno for x in nodes)-1
    lines=source.splitlines(keepends=True)
    updated=''.join(lines[:first])+EXTENSION+'\n'+''.join(lines[first:])
    compile(updated,str(path),'exec')
    path.write_text(updated,encoding='utf-8')
    print('[SHIFT BUILD 680 INSTALLED] Original-page extraction follows prepared index',flush=True)
if __name__=='__main__':apply(Path(sys.argv[1]))
