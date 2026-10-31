#!/usr/bin/env python3
"""Reuse one authenticated Bodgybros SFTP connection per TCREW roster sync.

Apply after roster_sftp_publish_20261101_patch.py. Keeps upload hashes,
manifest validation, unchanged-PDF handling, per-file retries and cache guard.
"""
import ast
import os
import sys
from pathlib import Path

MARKER='# SPR_ROSTER_SFTP_CONNECTION_REUSE_20261101'
ADDITIONS=r'''
# A roster update is already serialised by SHAREPOINT_BROWSE_LOCK. Reuse its
# authenticated SSH connection instead of connecting for every small PDF.
_ROSTER_SFTP_CONNECT_FRESH = _roster_sftp_connection
_ROSTER_SFTP_PER_THREAD = threading.local()

class _RosterSftpBorrowed:
    def __init__(self, wrapped): self._wrapped=wrapped
    def __getattr__(self,key): return getattr(self._wrapped,key)
    def close(self): pass  # owned by sync_all_rosters_online until manifest commit

def _roster_sftp_connection():
    cached=getattr(_ROSTER_SFTP_PER_THREAD,'connection',None)
    if cached is None:
        cached=_ROSTER_SFTP_CONNECT_FRESH()
        _ROSTER_SFTP_PER_THREAD.connection=cached
        print('[SFTP ROSTER SESSION OPEN] single connection for this update',flush=True)
    ssh,sftp,root=cached
    return _RosterSftpBorrowed(ssh),_RosterSftpBorrowed(sftp),root

def _roster_sftp_release():
    cached=getattr(_ROSTER_SFTP_PER_THREAD,'connection',None)
    _ROSTER_SFTP_PER_THREAD.connection=None
    if cached:
        ssh,sftp,_=cached
        try:sftp.close()
        except Exception:pass
        try:ssh.close()
        except Exception:pass
        print('[SFTP ROSTER SESSION CLOSED]',flush=True)

def _store_roster_fast(pdf_url,pdf_name,data,cache_path):
    """Bounded SFTP retries in the roster thread; no per-PDF worker thread."""
    last=None
    for attempt in range(3):
        _check_online_cancel()
        if attempt:
            pause=(2,5)[attempt-1]
            print(f'    [SFTP ROSTER RETRY {attempt+1}/3] {pdf_name}: {pause}s',flush=True)
            _set_online_progress(f'Roster SFTP retry: {pdf_name} ({attempt+1}/3)')
            time.sleep(pause)
        try:
            return upload_cached_roster_pdf(pdf_url,pdf_name,data,cache_path)
        except Exception as exc:
            last=exc
            print(f'    [SFTP ROSTER ATTEMPT FAILED {attempt+1}/3] {pdf_name}: {exc}',flush=True)
            _roster_sftp_release()  # stale connection is never reused on retry
    raise RuntimeError(f'Could not SFTP-store {pdf_name} after 3 attempts: {last}')

_ROSTER_SFTP_SYNC_ORIGINAL = sync_all_rosters_online

def sync_all_rosters_online():
    try:
        return _ROSTER_SFTP_SYNC_ORIGINAL()
    finally:
        _roster_sftp_release()
'''

def patch_file(path):
    source=path.read_text(encoding='utf-8')
    if MARKER in source:
        print('[ROSTER SFTP REUSE] Already installed',flush=True)
        return
    if '# SPR_ROSTER_SFTP_PUBLISH_VERIFIED_20261101' not in source:
        raise RuntimeError('Cannot reuse SFTP session: verified SFTP publishing patch absent')
    funcs={n.name for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
    if not {'upload_cached_roster_pdf','publish_roster_manifest','_store_roster_fast',
            '_roster_sftp_connection','sync_all_rosters_online'}.issubset(funcs):
        raise RuntimeError('Expected SFTP roster functions unavailable')
    if source.count('if __name__=="__main__":')!=1:
        raise RuntimeError('Updater entrypoint unexpected')
    source=source.replace('if __name__=="__main__":',ADDITIONS+'\nif __name__=="__main__":',1)
    source=MARKER+'\n'+source
    compile(source,str(path),'exec')
    tmp=path.with_suffix(path.suffix+'.sftp-reuse')
    tmp.write_text(source,encoding='utf-8')
    os.replace(tmp,path)
    print('[ROSTER SFTP REUSE READY] One session per sync; verification and retries preserved',flush=True)

if __name__=='__main__':
    patch_file(Path(sys.argv[1]))
