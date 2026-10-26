#!/usr/bin/env python3
"""Build 688: preserve previously verified Guards 26-Oct-2026 after wrong-role SharePoint download.
Run after all earlier updater patches. Never changes frontend/PDFs/rosters on installation.
"""
import ast
import sys
from pathlib import Path

MARKER='# SPR_GUARD_EXISTING_SOURCE_688'
HELPER=r'''
# SPR_GUARD_EXISTING_SOURCE_688
def _spr688_preserve_known_good_guard(day):
    # Only the known 26 Oct mislabeled SharePoint file, never blanket skip.
    if day.isoformat()!='2026-10-26':return False
    try:
        metadata=_spr686_read_guard_meta(day)
        sha=str(metadata.get('sourceSha') or '')
        valid=(metadata.get('roleValidated') is True and
               metadata.get('date')==day.isoformat() and
               metadata.get('role')=='guard' and
               re.fullmatch(r'[0-9a-fA-F]{64}',sha) is not None)
        if not valid:
            print('  [GUARD PRESERVE REFUSED] No verified Guards metadata',flush=True)
            return False
        if not _spr_primary_index_current(day.isoformat(),'guard',sha):
            print('  [GUARD PRESERVE REFUSED] Existing Guards index mismatch',flush=True)
            return False
        print('  [GUARD SOURCE VERIFIED] '+day.isoformat()+' existing Guards index role and checksum verified; wrong SharePoint source rejected',flush=True)
        return True
    except Exception as exc:
        print('  [GUARD PRESERVE REFUSED] '+type(exc).__name__+': '+str(exc).splitlines()[0][:100],flush=True)
        return False
'''
def once(block,old,new,label):
    if block.count(old)!=1:
        raise RuntimeError('688 mismatch '+label+' '+str(block.count(old)))
    return block.replace(old,new,1)
def patch(block):
    block=once(block,
        '                uploaded=[]\n                downloaded=[]\n                skipped=[]',
        '                uploaded=[]\n                downloaded=[]\n                retained=[]\n                skipped=[]','counters')
    block=once(block,
        '                        upload_pdf(site, directory, pdf, cfg, page)\n                        uploaded.append(exact_name)',
        '''                        try:
                            upload_pdf(site, directory, pdf, cfg, page)
                        except RuntimeError as invalid:
                            if (role=='Guards' and folder_date.isoformat()=='2026-10-26'
                                and 'Reject guard upload: source PDF printed role mismatch' in str(invalid)
                                and _spr688_preserve_known_good_guard(folder_date)):
                                # Keep known-good remote original and index, do not queue wrong SHA.
                                retained.append(exact_name)
                                print('  [GUARDS EXISTING PRESERVED] '+exact_name+' original PDF and index unchanged',flush=True)
                            else:
                                raise
                        else:
                            uploaded.append(exact_name)''','upload path')
    block=once(block,
        '                if skipped: parts.append("not available: "+", ".join(skipped))',
        '                if retained: parts.append("existing verified (unchanged): "+", ".join(retained))\n                if skipped: parts.append("not available: "+", ".join(skipped))','status details')
    block=once(block,'len(uploaded)==expected)',
        '(len(uploaded)+len(retained))==expected)','completion')
    block=once(block,
        '                summary=f"{len(uploaded)}/{expected} PDFs uploaded ({len(downloaded)} downloaded)"',
        '                summary=f"{len(uploaded)} uploaded, {len(retained)} existing verified of {expected} PDFs ({len(downloaded)} downloaded)"','summary')
    block=once(block,
        '                    "files_uploaded":len(uploaded),"files_failed":',
        '                    "files_uploaded":len(uploaded),"files_retained":len(retained),"files_failed":','result counts')
    return block
def apply(path):
    src=path.read_text(encoding='utf-8')
    if MARKER in src:
        print('[GUARD SOURCE PRESERVE 688] Already installed',flush=True)
        return
    t=ast.parse(src)
    lines=src.splitlines(keepends=True)
    candidates=[]
    for n in t.body:
        if not isinstance(n,ast.FunctionDef) or n.name!='run_update':continue
        block=''.join(lines[n.lineno-1:n.end_lineno])
        if 'downloaded=[]' in block and 'files_expected' in block and 'upload_pdf(site, directory, pdf, cfg, page)' in block:
            candidates.append(n)
    if len(candidates)!=1:
        raise RuntimeError('Expected one verified-completion SharePoint update method, found '+str(len(candidates)))
    if not all(x in src for x in ('def _spr686_read_guard_meta(', 'def _spr_primary_index_current(', 'def _spr686_check_pdf_role(')):
        raise RuntimeError('Existing Guards role and index verification unavailable')
    n=candidates[0]
    patched=patch(''.join(lines[n.lineno-1:n.end_lineno]))
    new=''.join(lines[:n.lineno-1])+patched.rstrip()+'\n'+''.join(lines[n.end_lineno:])
    newtree=ast.parse(new)
    positions=[n.lineno-1 for n in newtree.body if isinstance(n,ast.If) and '__name__' in (ast.get_source_segment(new,n.test) or '')]
    if not positions:raise RuntimeError('Missing updater entrypoint')
    newlines=new.splitlines(keepends=True)
    complete=''.join(newlines[:min(positions)])+'\n'+HELPER+'\n'+''.join(newlines[min(positions):])
    compile(complete,str(path),'exec')
    path.write_text(complete,encoding='utf-8')
    print('[GUARD SOURCE PRESERVE 688 READY] Wrong-role 26 Oct guarded fallback with accurate counts',flush=True)
if __name__=='__main__':apply(Path(sys.argv[1]))
