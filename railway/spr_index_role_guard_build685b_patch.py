#!/usr/bin/env python3
"""Build 685: enforce real Driver/Guard heading in EVERY published SPR index.

Applied after Bodgybros-only Build 674 preindex patch, with exact AST-targeted
replacements. Leaves source PDF uploads/rosters and Shift PDF viewer unchanged.
- Never trust only payload.role: validate underlying printed page headings.
- Use dedicated ?spr_preindex=1 so browser auto-restore cannot hijack indexer.
- Require roleValidated in SFTP metadata for indexes to count as current.
- Automatically rebuild current Sydney day's Guards index if unvalidated.
"""
from pathlib import Path
import ast,sys,re
MARKER='# SPR_ROLE_SOURCE_VALIDATE_BUILD685'
EXTRA=r'''
# SPR_ROLE_SOURCE_VALIDATE_BUILD685
def _spr685_validate_role_pages(payload,role):
    if role not in ('driver','guard'):raise RuntimeError('Unexpected index role')
    seen={'driver':0,'guard':0}
    for page in (payload.get('pages') or [])[:24]:
        if not isinstance(page,dict):continue
        head=str(page.get('text') or '')[:320]
        m=re.search(r'\bSydney\s+Trains?\s+(Driver|Guard)\b',head,re.I)
        if m:seen[m.group(1).lower()]+=1
    if not seen[role] or seen['guard' if role=='driver' else 'driver']:
        raise RuntimeError('Role identity mismatch: index requested '+role+
            ', printed source SPR pages show '+str(seen)+
            '. Refusing to publish mislabeled index')
    print(f'  [INDEX ROLE VERIFIED] {payload.get("date")} {role}: {seen[role]} matching header(s)',flush=True)

def _spr685_repair_guard():
    """Repair only the current Guards index in background, no source re-upload."""
    import datetime,io,base64,posixpath,json,paramiko
    from zoneinfo import ZoneInfo
    time.sleep(3)
    date=datetime.datetime.now(ZoneInfo('Australia/Sydney')).date().isoformat()
    env=os.environ
    role='guard'
    try:
        key_text=base64.b64decode(env['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
        key=None
        for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
            try:key=typ.from_private_key(io.StringIO(key_text));break
            except Exception:pass
        if key is None:raise RuntimeError('Primary SFTP key unavailable')
        pdfdir=_spr_remote_subdir(env['SFTP_ROOT'],'guards')
        meta_path=posixpath.join(posixpath.dirname(pdfdir),'i','g',date+'.meta.json')
        ssh=paramiko.SSHClient()
        ssh.load_host_keys(str(DATA_ROOT/'credentials'/'spr-sftp-known_hosts'))
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            ssh.connect(hostname=env['SFTP_HOST'],port=int(env.get('SFTP_PORT') or 22),
                username=env['SFTP_USERNAME'],pkey=key,timeout=12,auth_timeout=12,
                banner_timeout=12,allow_agent=False,look_for_keys=False)
            with ssh.open_sftp() as ftp:
                with ftp.open(meta_path,'rb') as f:meta=json.loads(f.read(65536))
        finally:ssh.close()
        sha=str(meta.get('sourceSha') or '')
        if not re.fullmatch('[0-9a-fA-F]{64}',sha):
            raise RuntimeError('Guard source PDF checksum unavailable')
        if meta.get('roleValidated') is True:
            print(f'  [INDEX ROLE REPAIR] {date} guards already role-verified',flush=True)
            return
        print(f'  [INDEX ROLE REPAIR START] {date} guard: rebuilding from Guards source PDF',flush=True)
        _spr_index_background([{'date':date,'role':'guard','sha':sha,'site':'https://www.bodgybros.com/sps'}])
        if _spr_primary_index_current(date,'guard',sha):
            print(f'  [INDEX ROLE REPAIR COMPLETE] {date} Guards index validated',flush=True)
        else:
            print(f'  [INDEX ROLE REPAIR INCOMPLETE] {date} Guards index not published; old wrong index cannot pass frontend validation',flush=True)
    except FileNotFoundError:
        print(f'  [INDEX ROLE REPAIR] {date} Guard metadata unavailable; next SPR update will rebuild',flush=True)
    except Exception as exc:
        print(f'  [INDEX ROLE REPAIR FAILED] {date}: {type(exc).__name__}: {str(exc)[:190]}',flush=True)

threading.Thread(target=_spr685_repair_guard,daemon=True,name='spr-guard-index-role-repair').start()
print('  [INDEX ROLE GUARD 685 READY] Guard and Driver page headings verified before publishing',flush=True)
'''
def set_func(code,tree,name,edits):
    funcs=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==name]
    if not funcs:raise RuntimeError('Missing installed Bodgybros pre-index function '+name)
    n=funcs[-1]
    lines=code.splitlines(keepends=True)
    fragment=''.join(lines[n.lineno-1:n.end_lineno])
    for before,after,label in edits:
        count=fragment.count(before)
        if count!=1:raise RuntimeError(f'{name} expected {label} once, found {count}')
        fragment=fragment.replace(before,after,1)
    return ''.join(lines[:n.lineno-1])+fragment+''.join(lines[n.end_lineno:])
def main(path):
    source=path.read_text(encoding='utf-8')
    if MARKER in source:
        print('Index role validation Build 685 already installed',flush=True)
        return
    if 'def _spr_primary_index_current(' not in source:
        raise RuntimeError('Expected existing Bodgybros-only preindex baseline not present')
    source=set_func(source,ast.parse(source),'_spr_publish_index',[
        ("page.goto(site+'/',wait_until='domcontentloaded',timeout=45000)",
         "page.goto(site+'/?spr_preindex=1',wait_until='domcontentloaded',timeout=45000)",
         'disable cross-role device restore in index browser'),
        ("    payload['sourceSha']=sha",
         "    _spr685_validate_role_pages(payload,role)\n    payload['sourceSha']=sha",
         'validate real source page role before publishing')])
    source=set_func(source,ast.parse(source),'_spr_publish_index_primary_sftp',[
        ("'updatedAt':int(time.time()),'compressedBytes':len(compressed)",
         "'updatedAt':int(time.time()),'compressedBytes':len(compressed),\n                'roleValidated':True",
         'new metadata proves source header checked')])
    source=set_func(source,ast.parse(source),'_spr_primary_index_current',[
        ("meta.get('pageLayoutBuild')==595 and",
         "meta.get('pageLayoutBuild')==595 and\n                    meta.get('roleValidated') is True and",
         'do not trust historical index without role proof')])
    tree=ast.parse(source)
    main_blocks=[node for node in tree.body if isinstance(node,ast.If) and
       '__name__' in (ast.get_source_segment(source,node.test) or '')]
    if not main_blocks:raise RuntimeError('Updater main boundary not found')
    offset=min(n.lineno for n in main_blocks)-1
    lines=source.splitlines(keepends=True)
    fixed=''.join(lines[:offset])+EXTRA+'\n'+''.join(lines[offset:])
    compile(fixed,str(path),'exec')
    path.write_text(fixed,encoding='utf-8')
    print('[INDEX GUARD BUILD 685 INSTALLED] Verify role before publication; auto-repair current Guards index',flush=True)
if __name__=='__main__':main(Path(sys.argv[1]))
