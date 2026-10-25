#!/usr/bin/env python3
"""Build 686 — block Driver/Guard mispublishes, repair today's Guards SPR.

Applies after existing Bodgybros-only SFTP upload/index and Build 685 role
identity guards. Only source PDFs with a confirmed printed crew role can
be published. A daemon performs one bounded Guards-only refresh from the
configured SharePoint folder, without overwriting on mismatch or errors.
Keeps roster updater, shift 684 text-preserving extraction, and driver data.
"""
import ast,sys
from pathlib import Path
MARKER="# SPR_SOURCE_ROLE_GUARD_686"
EXTRA=r'''
# SPR_SOURCE_ROLE_GUARD_686
from zoneinfo import ZoneInfo as _spr686_tz
from datetime import timedelta as _spr686_timedelta
from urllib.parse import urljoin as _spr686_urljoin
import hashlib as _spr686_hash
from pypdf import PdfReader as _spr686_reader

def _spr686_check_pdf_role(pdf,role):
    """Validate actual printable PDF content, not renamed file/meta/index."""
    expected='driver' if role in ('drivers','driver') else 'guard' if role in ('guards','guard') else ''
    if not expected:raise RuntimeError('Unknown SPR crew role')
    seen={'driver':0,'guard':0}
    reader=_spr686_reader(str(pdf),strict=False)
    if len(reader.pages)<10:raise RuntimeError('SPR document has too few pages')
    for i in range(min(8,len(reader.pages))):
        txt=(reader.pages[i].extract_text() or '')[:1400]
        m=re.search(r'\bSydney\s+Trains?\s+(Driver|Guard)\b',txt,re.I)
        if m:seen[m.group(1).lower()]+=1
    other='guard' if expected=='driver' else 'driver'
    if seen[expected]<2 or seen[other]:
        raise RuntimeError('Reject '+expected+' upload: source PDF printed role mismatch '+str(seen))
    print('  [SPR SOURCE ROLE VERIFIED] '+expected+': '+str(seen[expected])+' matching printed pages',flush=True)
    return True

_SPR686_ORIGINAL_UPLOAD=upload_pdf
def upload_pdf(site,role,pdf,cfg,page=None):
    _spr686_check_pdf_role(pdf,role)
    return _SPR686_ORIGINAL_UPLOAD(site,role,pdf,cfg,page)

def _spr686_repair_today_guards():
    from playwright.sync_api import sync_playwright
    today=datetime.now(_spr686_tz('Australia/Sydney')).date()
    target_date=today
    prefix='All Guards Combined'
    date_text=today.strftime('%d_%m_%Y')
    cfg=load_config()
    guard_root=str(cfg.get('guards_url') or '')
    driver_root=str(cfg.get('drivers_url') or '')
    if not guard_root or not driver_root or guard_root==driver_root:
        print('  [GUARDS REPAIR BLOCKED] Distinct SharePoint guard folder not configured',flush=True)
        return
    # Check for the source PDF with a validated published index; no need to
    # redownload if both source and index are known correct.
    try:
        meta=_spr686_read_guard_meta(today)
        if meta.get('roleValidated') is True:
            print('  [GUARDS REPAIR] Current index is already role verified',flush=True)
            return
    except Exception:pass
    print('  [GUARDS REPAIR START] '+date_text+' from configured Guards SharePoint folder',flush=True)
    selected=None
    sha=None
    with SHAREPOINT_BROWSE_LOCK, sync_playwright() as pw:
        context=_launch_sharepoint_context(pw,cfg,
            headless=str(os.environ.get('SPR_HEADLESS','0')).lower() in ('1','true','yes','on'),
            ignore_https_errors=True,accept_downloads=True,
            args=['--window-size=640,480','--window-position=20,20'],no_viewport=True)
        try:
            page=context.pages[0] if context.pages else context.new_page()
            page.goto(guard_root,wait_until='domcontentloaded',timeout=120000)
            if not _sharepoint_session_ready(page):
                _wait_for_sharepoint_signin(page,timeout_seconds=120)
            targets,err=eligible_targets(page,guard_root,prefix)
            if err:raise RuntimeError('Guard folder not found: '+str(err)[:160])
            matching=[href for d,href in targets if d==target_date]
            if not matching:raise RuntimeError('Dated Guards folder not present: '+date_text)
            folder=_spr686_urljoin(page.url,matching[0])
            page.goto(folder,wait_until='domcontentloaded',timeout=120000)
            page.wait_for_timeout(1000)
            candidates=[]
            # SharePoint's virtualized page rows can display "All Guards"
            # while their first anchor still targets a Drivers file. Read
            # actual server-side folder metadata first instead of trusting
            # a visible label/anchor association.
            try:
                from urllib.parse import urlparse,parse_qs,unquote
                roots=[]
                for value in (folder,guard_root):
                    u=urlparse(value)
                    q=parse_qs(u.query)
                    for field in ('id','RootFolder','rootfolder'):
                        for v in q.get(field,[]):
                            decoded=unquote(v).rstrip('/')
                            if decoded.startswith('/sites/') and decoded not in roots:
                                roots.append(decoded)
                    path=unquote(u.path or '').rstrip('/')
                    if path.lower().endswith('.aspx'):
                        path=path.rsplit('/',1)[0]
                    if path.lower().endswith('/forms'):
                        path=path.rsplit('/',1)[0]
                    if path.startswith('/sites/') and path not in roots:
                        roots.append(path)
                checked=set()
                candidates_api=[]
                for rel in roots[:8]:
                    if rel in checked:continue
                    checked.add(rel)
                    try:
                        api=_sharepoint_api_items(page,rel)
                    except Exception as exc:
                        print('  [GUARDS REPAIR API PATH FAILED] '+type(exc).__name__,flush=True)
                        continue
                    files=api.get('files') or []
                    folders=api.get('folders') or []
                    print('  [GUARDS REPAIR FOLDER API] files='+str(len(files))+' folders='+str(len(folders))+' depth=0',flush=True)
                    for entry in files:
                        name=str(entry.get('Name') or '')
                        server=str(entry.get('ServerRelativeUrl') or '')
                        if server and sharepoint_combined_pdf_matches(name,server,prefix,target_date):
                            candidates_api.append({'text':name,'href':server})
                    for entry in folders[:80]:
                        name=str(entry.get('Name') or '')
                        server=str(entry.get('ServerRelativeUrl') or '')
                        if not server or server in checked:continue
                        if date_from_name(name)!=target_date:continue
                        checked.add(server)
                        try:
                            inner=_sharepoint_api_items(page,server)
                            entries=inner.get('files') or []
                            print('  [GUARDS REPAIR FOLDER API] files='+str(len(entries))+' depth=1',flush=True)
                            for obj in entries:
                                name2=str(obj.get('Name') or '')
                                relative=str(obj.get('ServerRelativeUrl') or '')
                                if relative and sharepoint_combined_pdf_matches(name2,relative,prefix,target_date):
                                    candidates_api.append({'text':name2,'href':relative})
                        except Exception as exc:
                            print('  [GUARDS REPAIR API SUBFOLDER FAILED] '+type(exc).__name__,flush=True)
                for doc in candidates_api:
                    print('  [GUARDS REPAIR API MATCH] Named Guard PDF found on SharePoint',flush=True)
                    candidates.append(doc)
            except Exception as exc:
                print('  [GUARDS REPAIR API UNAVAILABLE] '+type(exc).__name__+': '+str(exc).splitlines()[0][:110],flush=True)
            for a in page.locator('a[href]').all():
                try:
                    label=' '.join(((a.inner_text(timeout=250) or '')+' '+(a.get_attribute('aria-label') or '')+' '+(a.get_attribute('title') or '')).split())
                    href=a.get_attribute('href') or ''
                    if href and sharepoint_combined_pdf_matches(label,href,prefix,target_date):
                        candidates.append({'text':prefix+' '+date_text+'.pdf','href':href})
                except Exception:pass
            for row in page.locator('[role="row"],[data-automationid="DetailsRow"]').all():
                try:
                    label=' '.join((row.inner_text(timeout=350) or '').split())
                    a=row.locator('a[href]').first
                    if a.count():
                        href=a.get_attribute('href') or ''
                        if href and sharepoint_combined_pdf_matches(label,href,prefix,target_date):
                            candidates.append({'text':prefix+' '+date_text+'.pdf','href':href})
                except Exception:pass
            unique=[]
            seen=set()
            for candidate in candidates:
                href=candidate['href']
                if href not in seen:seen.add(href);unique.append(candidate)
            print('  [GUARDS REPAIR CANDIDATES] '+str(len(unique)),flush=True)
            for index,item in enumerate(unique[:25],1):
                try:
                    page.goto(folder,wait_until='domcontentloaded',timeout=120000)
                    out=download_with_browser(page,item,prefix)
                    _spr686_check_pdf_role(out,'guards')
                    selected=out
                    with out.open('rb') as f:sha=_spr686_hash.file_digest(f,'sha256').hexdigest()
                    print('  [GUARDS REPAIR SOURCE FOUND] Candidate '+str(index)+' printed pages verified',flush=True)
                    break
                except Exception as err:
                    print('  [GUARDS REPAIR REJECTED] Candidate '+str(index)+' '+type(err).__name__+': '+str(err).splitlines()[0][:120],flush=True)
            if selected is None:
                raise RuntimeError('No downloadable correctly labelled Guards PDF; source file remains unchanged')
            final=selected.with_name(prefix+' '+date_text+'.pdf')
            if selected!=final:
                if final.exists():final.unlink()
                selected.rename(final)
                selected=final
            upload_pdf('https://www.bodgybros.com/sps','guards',selected,cfg,page)
            print('  [GUARDS REPAIR UPLOADED] '+date_text+' original Guard PDF SFTP verified',flush=True)
        finally:
            context.close()
            _wait_for_sharepoint_profile_release(6)
    if selected is not None:
        try:selected.unlink()
        except Exception:pass
        # The source is now correct: build the index from the actual Guard PDF.
        print('  [GUARDS REPAIR REINDEX] '+date_text,flush=True)
        _spr_index_background([{'date':today.isoformat(),'role':'guard',
            'sha':sha,'site':'https://www.bodgybros.com/sps'}])
        if _spr_primary_index_current(today.isoformat(),'guard',sha):
            print('  [GUARDS REPAIR COMPLETE] Correct source PDF and index both verified',flush=True)
        else:
            print('  [GUARDS REPAIR INDEX PENDING] Source PDF corrected; index not yet verified',flush=True)

def _spr686_read_guard_meta(day):
    import json,io,base64,posixpath,paramiko
    env=os.environ
    root=env['SFTP_ROOT']
    folder=_spr_remote_subdir(root,'guards')
    remote=posixpath.join(posixpath.dirname(folder),'i','g',day.isoformat()+'.meta.json')
    raw=base64.b64decode(env['SFTP_PRIVATE_KEY_B64']).decode()
    key=None
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=cls.from_private_key(io.StringIO(raw));break
        except Exception:pass
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(DATA_ROOT/'credentials'/'spr-sftp-known_hosts'))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=env['SFTP_HOST'],port=int(env.get('SFTP_PORT') or 22),
            username=env['SFTP_USERNAME'],pkey=key,
            timeout=12,auth_timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
        with ssh.open_sftp() as ftp:
            with ftp.open(remote,'rb') as f:return json.loads(f.read(65536))
    finally:ssh.close()


def _spr686_direct_guard26():
    """Try the actual SharePoint subweb API and exact paths for one date."""
    from playwright.sync_api import sync_playwright
    from urllib.parse import urlparse,parse_qs,unquote,quote
    import tempfile,hashlib,posixpath
    from datetime import date
    target=date(2026,10,26)
    cfg=load_config()
    url=str(cfg.get('guards_url') or '')
    if not url:raise RuntimeError('No Guards SharePoint source configured')
    parsed=urlparse(url)
    origin=parsed.scheme+'://'+parsed.netloc
    guard_root=unquote((parse_qs(parsed.query).get('RootFolder') or [''])[0]).rstrip('/')
    if not guard_root.lower().endswith('/guards'):
        raise RuntimeError('Incorrect configured Guards root')
    parent=unquote(parsed.path)
    site_root=parent.split('/Shared Documents_1/')[0]
    if not site_root or site_root==parent:
        raise RuntimeError('SharePoint subweb path could not be determined')
    site_apis=[origin+quote(site_root,safe='/')+'/_api/web',
               origin+'/sites/ST-SPS-SD/_api/web']
    dayfolders=[]
    # Prefer exact parent folder metadata returned by the SharePoint subweb,
    # but probe known date formats if the library view is virtualized.
    for datepart in ('26-10-2026','26_10_2026','26.10.2026'):
        dayfolders.append(guard_root+'/'+datepart)
    pdfpaths=[]
    depotpaths=[]
    seen=set()
    def add_pdf(p):
        p=unquote(str(p or ''))
        if p in seen or not p.lower().endswith('.pdf'):return
        if not p.lower().startswith(guard_root.lower()+'/'):return
        # Date-folder membership and actual printed Guards pages are the
        # identity checks; accept alternate filenames in the correct folder.
        basename=posixpath.basename(p)
        if date_from_name(basename) and date_from_name(basename)!=target:return
        if not any(p.lower().startswith(f.lower()+'/') for f in dayfolders):return
        seen.add(p);pdfpaths.append(p)
    with SHAREPOINT_BROWSE_LOCK, sync_playwright() as pw:
        context=_launch_sharepoint_context(pw,cfg,
            headless=str(os.environ.get('SPR_HEADLESS','0')).lower() in ('1','true','yes','on'),
            ignore_https_errors=True,accept_downloads=True,
            args=['--window-size=640,480','--window-position=20,20'],no_viewport=True)
        try:
            page=context.pages[0] if context.pages else context.new_page()
            page.goto(url,wait_until='domcontentloaded',timeout=120000)
            if not _sharepoint_session_ready(page):
                _wait_for_sharepoint_signin(page,timeout_seconds=120)
            def rest_items(api_root,folder,kind):
                escaped=folder.replace("'","''")
                endpoint=(api_root+"/GetFolderByServerRelativePath(decodedUrl='"+
                    quote(escaped,safe="/-._~")+
                    "')/"+kind+"?$select=Name,ServerRelativeUrl&$top=5000")
                resp=context.request.get(endpoint,headers={'Accept':'application/json;odata=nometadata'},timeout=35000)
                if not resp.ok:
                    print('  [GUARD26 SHAREPOINT API] HTTP '+str(resp.status)+' '+kind,flush=True)
                    return []
                data=resp.json()
                return data.get('value') or data.get('d',{}).get('results') or []
            for api in site_apis:
                try:
                    children=rest_items(api,guard_root,'Folders')
                    print('  [GUARD26 SHAREPOINT FOLDERS] '+str(len(children)),flush=True)
                    for obj in children:
                        p=unquote(str(obj.get('ServerRelativeUrl') or ''))
                        if p.lower().startswith(guard_root.lower()+'/') and date_from_name(posixpath.basename(p))==target and p not in dayfolders:
                            dayfolders.insert(0,p)
                except Exception as exc:
                    print('  [GUARD26 SHAREPOINT FOLDERS ERROR] '+str(exc).splitlines()[0][:140],flush=True)
                for folder in dayfolders:
                    try:
                        files=rest_items(api,folder,'Files')
                        print('  [GUARD26 SHAREPOINT FILES] '+str(len(files)),flush=True)
                        if files:
                            print('  [GUARD26 FILE NAMES] '+repr([str(item.get('Name') or '')[:90] for item in files[:35]]),flush=True)
                        for item in files:
                            remote=unquote(str(item.get('ServerRelativeUrl') or ''))
                            if re.search(r'/Guard_[^/]+_26_10_2026\.pdf
                    except Exception as exc:
                        print('  [GUARD26 SHAREPOINT FILES ERROR] '+str(exc).splitlines()[0][:110],flush=True)
            for folder in dayfolders:
                for filename in ('All Guards Combined 26_10_2026.pdf',
                                 'All Guards Combined 26-10-2026.pdf',
                                 'All Guards Combined 26.10.2026.pdf'):
                    add_pdf(folder+'/'+filename)
            print('  [GUARD26 EXACT-PATH CANDIDATES] '+str(len(pdfpaths)),flush=True)
            from pathlib import Path
            with tempfile.TemporaryDirectory(prefix='guard26-') as tmp:
                temp=Path(tmp)
                source=None;sha=None
                for i,path in enumerate(pdfpaths):
                    endpoints=[origin+quote(path,safe='/')]
                    for api in site_apis:
                        endpoints.append(api+"/GetFileByServerRelativePath(decodedUrl='"+
                            quote(path.replace("'","''"),safe="/-._~")+
                            "')/$value")
                    for ep in endpoints:
                        try:
                            response=context.request.get(ep,timeout=45000)
                            if not response.ok:continue
                            payload=response.body()
                            if not payload.startswith(b'%PDF') or len(payload)<50000:continue
                            candidate=temp/('candidate'+str(i)+'.pdf')
                            candidate.write_bytes(payload)
                            _spr686_check_pdf_role(candidate,'guards')
                            source=candidate
                            sha=hashlib.sha256(payload).hexdigest()
                            break
                        except Exception as exc:
                            print('  [GUARD26 REJECTED PDF] '+type(exc).__name__+': '+str(exc).splitlines()[0][:140],flush=True)
                    if source:break
                # Build the full combined PDF from every depot report. A
                # single Guard depot PDF is not a valid combined SPR.
                expected={'LEPPINGTON_YARD','BLACKTOWN','CAMPBELLTOWN','CRONULLA',
                          'CENTRAL','MORTDALE','HORNSBY','RICHMOND','NORTH_SYDNEY',
                          'PENRITH','AUBURN_YARD','FLEMINGTON','WATERFALL'}
                found={}
                for path in depotpaths:
                    m=re.search(r'/Guard_(.+?)_26_10_2026\.pdf$',path,re.I)
                    if m and m.group(1).upper() in expected:found[m.group(1).upper()]=path
                if set(found)!=expected:
                    raise RuntimeError('Cannot safely combine: Guards depot PDFs missing '+repr(sorted(expected-set(found))))
                from pypdf import PdfReader,PdfWriter
                from io import BytesIO
                writer=PdfWriter()
                totalpages=0
                for depot in sorted(expected):
                    remote=found[depot]
                    response=context.request.get(origin+quote(remote,safe='/'),timeout=70000)
                    if not response.ok:raise RuntimeError('Guard depot PDF failed '+depot+' HTTP '+str(response.status))
                    data=response.body()
                    if not data.startswith(b'%PDF'):raise RuntimeError('Not a PDF: '+depot)
                    reader=PdfReader(BytesIO(data),strict=False)
                    if len(reader.pages)<1:raise RuntimeError('Empty Guards depot PDF: '+depot)
                    heading=(reader.pages[0].extract_text() or '')[:1400]
                    if not re.search(r'Sydney\s+Trains?\s+Guard\b',heading,re.I) or re.search(r'Sydney\s+Trains?\s+Driver\b',heading,re.I):
                        raise RuntimeError('Wrong printed role in Guards depot PDF: '+depot)
                    totalpages+=len(reader.pages)
                    writer.append(reader)
                    print('  [GUARD26 DEPOT VERIFIED] '+depot+' '+str(len(reader.pages))+' pages',flush=True)
                if totalpages<100:raise RuntimeError('Guards combined PDF too small: '+str(totalpages)+' pages')
                combined=temp/'all-guards-rebuilt.pdf'
                with combined.open('wb') as f:writer.write(f)
                writer.close()
                _spr686_check_pdf_role(combined,'guards')
                source=combined
                sha=hashlib.sha256(source.read_bytes()).hexdigest()
                print('  [GUARD26 COMBINED REBUILT] '+str(len(expected))+' Guards depots, '+str(totalpages)+' pages',flush=True)
                final=temp/'All Guards Combined 26_10_2026.pdf'
                source.replace(final)
                upload_pdf('https://www.bodgybros.com/sps','guards',final,cfg,page)
                print('  [GUARD26 UPLOADED] 26 October correct original Guards PDF verified by SFTP',flush=True)
        finally:
            context.close()
            _wait_for_sharepoint_profile_release(6)
    if sha:
        print('  [GUARD26 REINDEX] 2026-10-26 guard only',flush=True)
        _spr_index_background([{'date':'2026-10-26','role':'guard','sha':sha,
            'site':'https://www.bodgybros.com/sps'}])
        if _spr_primary_index_current('2026-10-26','guard',sha):
            print('  [GUARD26 COMPLETE] Source and index confirmed',flush=True)
        else:
            print('  [GUARD26 INDEX NOT VERIFIED] Source repaired, search index pending',flush=True)
        return True
    return False

_spr686_old_repair_today_guards=_spr686_repair_today_guards
def _spr686_repair_today_guards():
    try:
        if _spr686_direct_guard26():return
    except Exception as exc:
        print('  [GUARD26 DIRECT LOOKUP FAILED] '+type(exc).__name__+': '+str(exc).splitlines()[0][:170],flush=True)
    # Keep the existing guarded SharePoint browser workflow as fallback;
    # it also refuses Driver PDFs and never overwrites on failure.
    return _spr686_old_repair_today_guards()

def _spr686_guard_worker():
    try:_spr686_repair_today_guards()
    except Exception as exc:
        print('  [GUARDS REPAIR FAILED] '+type(exc).__name__+': '+str(exc).splitlines()[0][:220],flush=True)

# Do not race the Build 685 startup index repair. It exits on mismatched
# source pages, and this thread holds the SharePoint profile lock for fetch.
threading.Thread(target=_spr686_guard_worker,name='spr-guards-source-repair',daemon=True).start()
print('  [SPR SOURCE VALIDATION 686 READY] Guard and Driver PDFs checked before any SFTP or cPanel upload',flush=True)
'''
def apply(path):
 source=path.read_text(encoding='utf-8')
 if MARKER in source:
  print('SPR source role guard Build 686 already installed',flush=True);return
 t=ast.parse(source)
 if not all(any(isinstance(n,ast.FunctionDef) and n.name==k for n in t.body)
  for k in ('upload_pdf','_spr_index_background','_spr_primary_index_current','download_with_browser','eligible_targets')):
  raise RuntimeError('Expected SPR updater, SharePoint and SFTP preindex methods missing')
 starts=[n.lineno-1 for n in t.body if isinstance(n,ast.If) and '__name__' in (ast.get_source_segment(source,n.test) or '')]
 if not starts:raise RuntimeError('No service entrypoint found')
 i=min(starts)
 lines=source.splitlines(keepends=True)
 modified=''.join(lines[:i])+EXTRA+'\n'+''.join(lines[i:])
 compile(modified,str(path),'exec')
 path.write_text(modified,encoding='utf-8')
 print('[GUARDS SOURCE PATCH 686 INSTALLED] Validating PDF role before upload; repairing current Guards SPR',flush=True)
if __name__=='__main__':apply(Path(sys.argv[1]))
,remote,re.I) and remote not in depotpaths:
                                depotpaths.append(remote)
                            add_pdf(remote)
                    except Exception as exc:
                        print('  [GUARD26 SHAREPOINT FILES ERROR] '+str(exc).splitlines()[0][:110],flush=True)
            for folder in dayfolders:
                for filename in ('All Guards Combined 26_10_2026.pdf',
                                 'All Guards Combined 26-10-2026.pdf',
                                 'All Guards Combined 26.10.2026.pdf'):
                    add_pdf(folder+'/'+filename)
            print('  [GUARD26 EXACT-PATH CANDIDATES] '+str(len(pdfpaths)),flush=True)
            from pathlib import Path
            with tempfile.TemporaryDirectory(prefix='guard26-') as tmp:
                temp=Path(tmp)
                source=None;sha=None
                for i,path in enumerate(pdfpaths):
                    endpoints=[origin+quote(path,safe='/')]
                    for api in site_apis:
                        endpoints.append(api+"/GetFileByServerRelativePath(decodedUrl='"+
                            quote(path.replace("'","''"),safe="/-._~")+
                            "')/$value")
                    for ep in endpoints:
                        try:
                            response=context.request.get(ep,timeout=45000)
                            if not response.ok:continue
                            payload=response.body()
                            if not payload.startswith(b'%PDF') or len(payload)<50000:continue
                            candidate=temp/('candidate'+str(i)+'.pdf')
                            candidate.write_bytes(payload)
                            _spr686_check_pdf_role(candidate,'guards')
                            source=candidate
                            sha=hashlib.sha256(payload).hexdigest()
                            break
                        except Exception as exc:
                            print('  [GUARD26 REJECTED PDF] '+type(exc).__name__+': '+str(exc).splitlines()[0][:140],flush=True)
                    if source:break
                if source is None:
                    print('  [GUARD26 DIRECT SOURCE NOT FOUND] No correctly headed PDF; existing file preserved',flush=True)
                    return False
                final=temp/'All Guards Combined 26_10_2026.pdf'
                source.replace(final)
                upload_pdf('https://www.bodgybros.com/sps','guards',final,cfg,page)
                print('  [GUARD26 UPLOADED] 26 October correct original Guards PDF verified by SFTP',flush=True)
        finally:
            context.close()
            _wait_for_sharepoint_profile_release(6)
    if sha:
        print('  [GUARD26 REINDEX] 2026-10-26 guard only',flush=True)
        _spr_index_background([{'date':'2026-10-26','role':'guard','sha':sha,
            'site':'https://www.bodgybros.com/sps'}])
        if _spr_primary_index_current('2026-10-26','guard',sha):
            print('  [GUARD26 COMPLETE] Source and index confirmed',flush=True)
        else:
            print('  [GUARD26 INDEX NOT VERIFIED] Source repaired, search index pending',flush=True)
        return True
    return False

_spr686_old_repair_today_guards=_spr686_repair_today_guards
def _spr686_repair_today_guards():
    try:
        if _spr686_direct_guard26():return
    except Exception as exc:
        print('  [GUARD26 DIRECT LOOKUP FAILED] '+type(exc).__name__+': '+str(exc).splitlines()[0][:170],flush=True)
    # Keep the existing guarded SharePoint browser workflow as fallback;
    # it also refuses Driver PDFs and never overwrites on failure.
    return _spr686_old_repair_today_guards()

def _spr686_guard_worker():
    try:_spr686_repair_today_guards()
    except Exception as exc:
        print('  [GUARDS REPAIR FAILED] '+type(exc).__name__+': '+str(exc).splitlines()[0][:220],flush=True)

# Do not race the Build 685 startup index repair. It exits on mismatched
# source pages, and this thread holds the SharePoint profile lock for fetch.
threading.Thread(target=_spr686_guard_worker,name='spr-guards-source-repair',daemon=True).start()
print('  [SPR SOURCE VALIDATION 686 READY] Guard and Driver PDFs checked before any SFTP or cPanel upload',flush=True)
'''
def apply(path):
 source=path.read_text(encoding='utf-8')
 if MARKER in source:
  print('SPR source role guard Build 686 already installed',flush=True);return
 t=ast.parse(source)
 if not all(any(isinstance(n,ast.FunctionDef) and n.name==k for n in t.body)
  for k in ('upload_pdf','_spr_index_background','_spr_primary_index_current','download_with_browser','eligible_targets')):
  raise RuntimeError('Expected SPR updater, SharePoint and SFTP preindex methods missing')
 starts=[n.lineno-1 for n in t.body if isinstance(n,ast.If) and '__name__' in (ast.get_source_segment(source,n.test) or '')]
 if not starts:raise RuntimeError('No service entrypoint found')
 i=min(starts)
 lines=source.splitlines(keepends=True)
 modified=''.join(lines[:i])+EXTRA+'\n'+''.join(lines[i:])
 compile(modified,str(path),'exec')
 path.write_text(modified,encoding='utf-8')
 print('[GUARDS SOURCE PATCH 686 INSTALLED] Validating PDF role before upload; repairing current Guards SPR',flush=True)
if __name__=='__main__':apply(Path(sys.argv[1]))
