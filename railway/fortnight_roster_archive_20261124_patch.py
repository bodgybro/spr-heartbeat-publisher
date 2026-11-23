#!/usr/bin/env python3
"""Add immutable Sunday-start fortnight archives to the verified SFTP roster updater.

Apply after the existing SFTP-publish and SFTP-reuse patches. The live roster
paths and manifest stay unchanged. All snapshots are private to the existing
Bodgybros SFTP account; this does not itself add website archive browsing.
"""
from pathlib import Path
import ast
import os
import sys

MARKER = '# FORTNIGHT_ROSTER_ARCHIVE_20261124_V1'
EXTENSION = r'''
# FORTNIGHT_ROSTER_ARCHIVE_20261124_V1
# Sunday 15 Nov 2026 is the known beginning of this roster cycle. Keep
# 14-day boundaries before and after that date (including across years).
_ROSTER_ARCHIVE_EPOCH = '2026-11-15'
_ROSTER_ARCHIVE_UPLOAD_ORIGINAL = upload_cached_roster_pdf

def _roster_archive_fortnight(day):
    from datetime import date, timedelta
    anchor=date.fromisoformat(_ROSTER_ARCHIVE_EPOCH)
    if not isinstance(day,date):
        raise TypeError('Roster effective date must be a date')
    return (anchor+timedelta(days=((day-anchor).days//14)*14)).isoformat()

def _roster_archive_date_token(token):
    import re
    from datetime import datetime, date
    clean=' '.join(str(token).strip().replace(',', ' ').split())
    for fmt in ('%d/%m/%Y','%d/%m/%y','%d-%m-%Y','%d-%m-%y',
                '%Y-%m-%d','%d %b %Y','%d %B %Y','%d %b %y','%d %B %y'):
        try:
            d=datetime.strptime(clean,fmt).date()
            if date(2020,1,1)<=d<=date(2100,1,1):
                return d
        except ValueError:pass
    return None

def _roster_archive_effective_date(data,kind):
    """Reject ambiguous PDF headings; never guess a fortnight from upload time."""
    import io,re
    from pypdf import PdfReader
    if kind not in ('daily','period','fortnight'):
        raise ValueError('Unknown roster category')
    reader=PdfReader(io.BytesIO(data),strict=False)
    fragments=[]
    for page in reader.pages[:min(len(reader.pages),3)]:
        fragments.append((page.extract_text() or '')[:12000])
    text='\n'.join(fragments)
    date_pattern=(r'(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|'
                  r'\d{4}-\d{2}-\d{2}|'
                  r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
                  r'[a-z]*\s+\d{2,4})')
    heading_patterns=(
        r'(?i)\b(?:fortnight|period|roster)\s*(?:roster)?\s*'
        r'(?:commencing|starting|start date|from|beginning)\s*:?\s*('+date_pattern+r')',
        r'(?i)\b(?:week commencing|week starting)\s*:?\s*('+date_pattern+r')',
    )
    if kind=='daily':
        heading_patterns += (
            r'(?i)\b(?:roster date|date of roster|daily roster date)\s*:?\s*('+date_pattern+r')',
        )
    for pattern in heading_patterns:
        matches={_roster_archive_date_token(m.group(1)) for m in re.finditer(pattern,text)}
        matches.discard(None)
        if len(matches)==1:
            return next(iter(matches))
        if len(matches)>1:
            return None
    # A PDF containing days from exactly one fortnight can be safely grouped.
    dates={_roster_archive_date_token(m.group(0))
           for m in re.finditer(r'(?i)'+date_pattern,text[:18000])}
    dates.discard(None)
    keys={_roster_archive_fortnight(d) for d in dates}
    if len(keys)==1 and dates:
        # The earliest roster day is a stable name within that fortnight.
        return min(dates)
    return None

def _roster_archive_snapshot(sftp,site_root,parts,pdf_bytes):
    """Write immutable private snapshot; exact hash verified before success."""
    import hashlib,os,posixpath,stat,time
    if not pdf_bytes.startswith(b'%PDF') or len(pdf_bytes)>80_000_000:
        raise RuntimeError('Roster archive refused invalid or oversized PDF')
    sha=hashlib.sha256(pdf_bytes).hexdigest()
    date=None
    try:
        date=_roster_archive_effective_date(pdf_bytes,parts[2])
    except Exception as exc:
        print('[ROSTER ARCHIVE DATE UNCLASSIFIED] '+type(exc).__name__,flush=True)
    if date is None:
        directories=['.roster-cache','archives','unclassified']+parts[:3]
        name=sha+'.pdf'
    else:
        directories=(['.roster-cache','archives','fortnights',
                      _roster_archive_fortnight(date)]+parts[:3]+[date.isoformat()])
        name=sha+'.pdf'
    # Keep crew rosters outside the web document root; historical data must
    # only be served by a future authenticated roster-browser endpoint.
    import posixpath
    if (posixpath.basename(site_root)!='sps' or
            posixpath.basename(posixpath.dirname(site_root))!='public_html'):
        raise RuntimeError('Unexpected site root; cannot verify private archive location')
    account_root=posixpath.dirname(posixpath.dirname(site_root))
    directory=_roster_sftp_dirs(
        sftp,account_root,['sps-private-assets','roster-archives-v1']+directories[2:],
        private=True)
    target=posixpath.join(directory,name)
    try:
        info=sftp.stat(target)
        if not stat.S_ISREG(info.st_mode) or info.st_size!=len(pdf_bytes) or _roster_sftp_digest(sftp,target)!=sha:
            raise RuntimeError('Roster archive immutable file mismatch')
        return target,False
    except FileNotFoundError:
        pass
    tmp=target+'.pending-'+str(os.getpid())+'-'+str(time.time_ns())
    try:
        with sftp.open(tmp,'wb') as writer:
            for i in range(0,len(pdf_bytes),1024*1024):
                writer.write(pdf_bytes[i:i+1024*1024])
            writer.flush()
        sftp.chmod(tmp,0o600)
        if sftp.stat(tmp).st_size!=len(pdf_bytes) or _roster_sftp_digest(sftp,tmp)!=sha:
            raise RuntimeError('Roster archive temporary PDF verification failed')
        sftp.posix_rename(tmp,target)
        tmp=None
        if sftp.stat(target).st_size!=len(pdf_bytes) or _roster_sftp_digest(sftp,target)!=sha:
            raise RuntimeError('Roster archive final PDF verification failed')
    finally:
        if tmp is not None:
            try:sftp.remove(tmp)
            except Exception:pass
    return target,True

def upload_cached_roster_pdf(url,name,data,cache_path=''):
    """Archive both the soon-to-be-replaced PDF and incoming version first.

    Fail closed: an archive error stops replacement, keeping the previous live
    PDF intact. Existing atomic publishing and manifest checks then run normally.
    """
    import hashlib,posixpath,stat
    _roster_sftp_check_url(url)
    parts=_roster_valid_cache_path(cache_path)
    if name!=parts[-1] or not isinstance(data,(bytes,bytearray)) or data[:4]!=b'%PDF':
        raise RuntimeError('Archive input does not match validated live roster path')
    sha=hashlib.sha256(data).hexdigest()
    ssh,sftp,site_root=_roster_sftp_connection()
    try:
        current=posixpath.join(site_root,'rosters',*parts)
        old=None
        try:
            info=sftp.stat(current)
            if not stat.S_ISREG(info.st_mode) or not 4<=info.st_size<=80_000_000:
                raise RuntimeError('Existing roster file cannot be safely archived')
            with sftp.open(current,'rb') as source:
                old=source.read(80_000_001)
            if len(old)!=info.st_size or not old.startswith(b'%PDF'):
                raise RuntimeError('Existing roster content differs from stat; refusing overwrite')
        except FileNotFoundError:
            pass
        if old is not None and hashlib.sha256(old).hexdigest()!=sha:
            _roster_archive_snapshot(sftp,site_root,parts,old)
        _path,new=_roster_archive_snapshot(sftp,site_root,parts,data)
        if new:
            print('    [ROSTER ARCHIVE VERIFIED] '+cache_path+' '+sha[:12],flush=True)
    finally:
        try:sftp.close()
        finally:ssh.close()
    return _ROSTER_ARCHIVE_UPLOAD_ORIGINAL(url,name,data,cache_path)
'''

def apply(path):
    path=Path(path)
    src=path.read_text(encoding='utf-8')
    if MARKER in src:
        print('FORTNIGHT_ARCHIVE_ALREADY_INSTALLED',flush=True)
        return
    if '# SPR_ROSTER_SFTP_CONNECTION_REUSE_20261101' not in src:
        raise RuntimeError('Verified roster SFTP session-reuse patch required')
    funcs={n.name for n in ast.parse(src).body if isinstance(n,ast.FunctionDef)}
    required={'upload_cached_roster_pdf','_roster_sftp_connection',
              '_roster_sftp_dirs','_roster_sftp_digest',
              '_roster_valid_cache_path','_roster_sftp_check_url'}
    if not required.issubset(funcs):
        raise RuntimeError('Live roster SFTP interface changed; refusing to patch')
    marker='if __name__=="__main__":'
    if src.count(marker)!=1:
        raise RuntimeError('Expected exactly one updater entrypoint')
    src=src.replace(marker,EXTENSION+'\n'+marker,1)
    ast.parse(src)
    compile(src,str(path),'exec')
    tmp=path.with_name(path.name+'.archive-patch-new')
    tmp.write_text(src,encoding='utf-8')
    os.replace(tmp,path)
    print('FORTNIGHT_ARCHIVE_PATCH_PASS immutable_private=yes live_paths_unchanged=yes',flush=True)

if __name__=='__main__':
    if len(sys.argv)!=2:
        raise SystemExit('usage: fortnight_roster_archive_20261124_patch.py updater.py')
    apply(Path(sys.argv[1]))
