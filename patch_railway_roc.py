#!/usr/bin/env python3
"""Add a separate manual ROC command to the already-built SPR Railway updater.

Run AFTER the existing cloudflare_command_patch and roc_domo_noon_only patches.
Does not change scheduled ROC checks, SPR processing, or roster processing.
Fails safely before writing when expected hooks do not match.
"""
import ast
import pathlib
import sys

MARKER = '# ROC_MANUAL_COMMAND_20261114_V1'

def extract_top_func(src, name):
    tree = ast.parse(src)
    matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one '+name+' function, found '+str(len(matches)))
    lines=src.splitlines(keepends=True)
    node=matches[0]
    return lines, node, ''.join(lines[node.lineno-1:node.end_lineno])

def replace_func(src, name, replacement):
    lines,node,body=extract_top_func(src,name)
    lines[node.lineno-1:node.end_lineno] = [replacement.rstrip()+"\n"]
    return ''.join(lines)

HELPER = '''def _roc_manual_check():
    """Run the existing ROC downloader independently of SPR/roster updates."""
    from playwright.sync_api import sync_playwright
    import roc_domo_daily_worker_20261104 as roc_worker
    _check_online_cancel()
    _set_online_progress("ROC: opening authenticated SharePoint browser")
    cfg=load_config()
    with SHAREPOINT_BROWSE_LOCK:
        try:
            with sync_playwright() as p:
                browser=_launch_sharepoint_context(
                    p,cfg,
                    headless=str(os.environ.get("SPR_HEADLESS","0")).strip().lower() in
                        ("1","true","yes","on"),
                    ignore_https_errors=True,accept_downloads=True,
                    args=["--window-size=900,650","--window-position=20,20"],
                    no_viewport=True)
                try:
                    _check_online_cancel()
                    _set_online_progress("ROC: checking yesterday's CSV in SharePoint")
                    if not roc_worker.process(browser, globals()):
                        raise RuntimeError("ROC CSV check did not complete")
                    _check_online_cancel()
                finally:
                    browser.close()
        finally:
            _wait_for_sharepoint_profile_release()
    _set_online_progress("ROC: CSV verified on Bodgybros and Kustomvinyls")
    _record_online_success("roc")
    return [{"role":"ROC","message":"CSV checked and verified on both websites (new or existing)"}]
'''

def patch(src):
    if MARKER in src:
        raise RuntimeError('Manual ROC command patch is already present')
    for hook in ["def start_background_update(","def online_control_worker(","def _record_online_success(","SHAREPOINT_BROWSE_LOCK", "def _launch_sharepoint_context(","def _wait_for_sharepoint_profile_release("]:
        if hook not in src:raise RuntimeError('Required existing updater hook not found: '+hook)
    # Make sure the currently installed ROC noon-only patch is present, unchanged.
    if '# ROC_DOMO_NOON_ONLY_20261104_V2' not in src:
        raise RuntimeError('Noon-only ROC patch not present: preserving current updater')
    src=src.replace('def start_background_update(',HELPER+'\ndef start_background_update(',1)
    lines,node,fn=extract_top_func(src,'start_background_update')
    needle='            elif mode == "rosters":\n'
    if fn.count(needle)!=1:
        raise RuntimeError('Expected one manual rosters branch in start_background_update')
    fn=fn.replace(needle,'            elif mode == "roc":\n                result=_roc_manual_check()\n'+needle,1)
    src=replace_func(src,'start_background_update',fn)
    lines,node,fn=extract_top_func(src,'online_control_worker')
    needle='if tid and kind in ("spr","rosters"):'
    if fn.count(needle)!=1:
        raise RuntimeError('Expected one existing manual command allowlist in online_control_worker')
    fn=fn.replace(needle,'if tid and kind in ("spr","rosters","roc"):',1)
    needle='("Roster" if kind=="rosters" else "SPR")'
    if fn.count(needle)!=1:
        raise RuntimeError('Expected one initial command progress label')
    fn=fn.replace(needle,'("ROC" if kind=="roc" else ("Roster" if kind=="rosters" else "SPR"))',1)
    src=replace_func(src,'online_control_worker',fn)
    lines,node,fn=extract_top_func(src,'_record_online_success')
    needle='("spr","rosters")'
    if fn.count(needle)!=1:
        raise RuntimeError('Expected one success reporting allowlist')
    src=replace_func(src,'_record_online_success',fn.replace(needle,'("spr","rosters","roc")',1))
    patched=MARKER+'\n'+src
    ast.parse(patched)
    compile(patched,'roc_patched_updater.py','exec')
    return patched

def main():
    if len(sys.argv)!=2:raise SystemExit('Usage: python patch_railway_roc.py /app/spr_online_updater.py')
    p=pathlib.Path(sys.argv[1])
    before=p.read_text(encoding='utf-8')
    after=patch(before)
    # Write once after ALL structural and syntax checks have passed.
    p.write_text(after,encoding='utf-8')
    print('ROC manual command patched: existing noon schedule and other modes preserved')

if __name__=='__main__':
    main()
