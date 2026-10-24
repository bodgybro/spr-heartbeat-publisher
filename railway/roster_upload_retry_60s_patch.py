#!/usr/bin/env python3
"""Make individual TCREW roster cache uploads more tolerant of slow hosting.

Run after fast_roster_patch.py and the completion/recovery patches.
Only replaces _store_roster_fast; SPR/SFTP upload behaviour is unchanged.
"""
import ast
import sys
from pathlib import Path

MARKER = "# SPR_ROSTER_UPLOAD_TIMEOUT_60_RETRIES_3"
REPLACEMENT = '''def _store_roster_fast(pdf_url,pdf_name,data,cache_path):
    """Retry individual roster cache uploads; preserve strict completion counting."""
    attempts=3
    limit_seconds=60
    last=None
    for attempt in range(attempts):
        _check_online_cancel()
        if attempt:
            delay=(2,5)[attempt-1]
            print(f"    [UPLOAD RETRY {attempt+1}/{attempts}] {pdf_name}: waiting {delay}s",flush=True)
            _set_online_progress(f"Roster update: retrying {pdf_name} ({attempt+1}/{attempts})")
            time.sleep(delay)
            _check_online_cancel()
        try:
            result=_run_with_hard_timeout(
                lambda: upload_cached_roster_pdf(pdf_url,pdf_name,data,cache_path),
                limit_seconds,
                f"Roster cache upload {pdf_name}"
            )
            if attempt:
                print(f"    [UPLOAD RECOVERED {attempt+1}/{attempts}] {pdf_name}",flush=True)
            return result
        except Exception as e:
            last=e
            print(f"    [UPLOAD ATTEMPT FAILED {attempt+1}/{attempts}] {pdf_name}: {e}",flush=True)
    raise RuntimeError(f"Could not store {pdf_name} after {attempts} attempts ({limit_seconds}s timeout each): {last}")
'''

def apply(path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Roster upload retry patch already applied",flush=True)
        return
    tree=ast.parse(source)
    matches=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_store_roster_fast"]
    if len(matches)!=1:
        raise RuntimeError("Expected exactly one _store_roster_fast function; no changes made")
    n=matches[0]
    ls=source.splitlines(keepends=True)
    old="".join(ls[n.lineno-1:n.end_lineno])
    if "range(2)" not in old or "15," not in old or "_run_with_hard_timeout(" not in old:
        raise RuntimeError("Roster upload implementation differs from verified source; no changes made")
    patched="".join(ls[:n.lineno-1])+REPLACEMENT+"".join(ls[n.end_lineno:])
    patched=MARKER+"\n"+patched
    compile(patched,str(path),"exec")
    path.write_text(patched,encoding="utf-8")
    print("Roster cache uploads: 60s timeout, max 3 attempts, retry delays 2s/5s",flush=True)

if __name__=="__main__":
    apply(Path(sys.argv[1]))
