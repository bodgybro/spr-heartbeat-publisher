#!/usr/bin/env python3
"""Build 675: bound TCREW roster discovery and remove legacy unbounded scanners.

The original 'short fallback' patch only limited page.goto to 8 seconds.
A later fallback silently restored SharePoint frame/DOM walkers that can block
many minutes. Replace them with 4 bounded HTML reads, and skip/record an
unavailable depot rather than pinning the entire roster run.
No SPR, SFTP, scheduled-slot or roster-upload functions are changed.
"""
import ast
from pathlib import Path
import sys

MARKER='# SPR_ROSTER_BOUNDED_DISCOVERY_675'
def apply(path):
    source=path.read_text(encoding='utf-8')
    if MARKER in source:
        print('Build 675 roster discovery already active',flush=True)
        return
    tree=ast.parse(source)
    funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and
        n.name=='sync_all_rosters_online']
    if len(funcs)!=1:
        raise RuntimeError('Cannot locate unique roster synchronization function')
    node=funcs[0]
    lines=source.splitlines(keepends=True)
    block=''.join(lines[node.lineno-1:node.end_lineno])
    start=block.find('                    if missing:\n                        # The plain HTML shortcut')
    end=block.find('                    print("    Fast roster discovery found all 6 PDFs.",flush=True)',start)
    if start<0 or end<=start:
        raise RuntimeError('Expected legacy unbounded SharePoint fallback missing')
    safe_fallback='''                    if missing:
                        # Read at most four SharePoint frames. Every DOM read has
                        # a Playwright timeout; never call the old exhaustive
                        # frame or virtualised-row scanners from roster updates.
                        print(f"    [FALLBACK BOUNDED] {depot_name}: checking up to four HTML frames",flush=True)
                        _set_online_progress(f"Roster update: {depot_name} ({depot_index}/{len(depots)}) — checking embedded PDF links")
                        for fr_index,fr in enumerate(list(page.frames)[:4],1):
                            _check_online_cancel()
                            try:
                                html=fr.locator("html").inner_html(timeout=1800)
                                discovered+=_fast_roster_items_from_html(html,depot_url)
                            except Exception as frame_error:
                                detail=str(frame_error).splitlines()[0][:180]
                                print(f"    [FALLBACK FRAME {fr_index}] {detail}",flush=True)
                            missing=[f"{role} {period}" for role in roles for period in periods if not pick_pdf(discovered,role,period)]
                            if not missing:
                                break
                        if missing:
                            print(f"    [FALLBACK SKIPPED] {depot_name}: missing {', '.join(missing)}",flush=True)
                            _set_online_progress(f"Roster update: {depot_name} ({depot_index}/{len(depots)}) — missing links, continuing")
                            raise RuntimeError("Roster targets unavailable after bounded discovery: "+", ".join(missing))
'''
    block=block[:start]+safe_fallback+block[end:]
    old='discovered += _fast_roster_items_from_html(page.content(),depot_url)'
    new='discovered += _fast_roster_items_from_html(page.locator("html").inner_html(timeout=2500),depot_url)'
    if block.count(old)!=1:
        raise RuntimeError('Expected unbounded page.content() call not found')
    block=block.replace(old,new,1)
    old_log='print(f"    Direct depot read failed quickly: {e}",flush=True)'
    if block.count(old_log)!=1:
        raise RuntimeError('Expected direct request error log not found')
    block=block.replace(old_log,
        'print(f"    Direct depot read failed quickly: {str(e).splitlines()[0][:180]}",flush=True)')
    old_nav='print(f"    Depot page fallback stopped: {nav_error}",flush=True)'
    if block.count(old_nav)!=1:
        raise RuntimeError('Expected fallback navigation error log not found')
    block=block.replace(old_nav,
        'print(f"    Depot page fallback stopped: {str(nav_error).splitlines()[0][:180]}",flush=True)')
    if '_sharepoint_rendered_items(page,depot_url)' in block or '_sharepoint_embedded_roster_items(page,depot_url)' in block:
        raise RuntimeError('Unbounded scanner references remain in active roster sync')
    updated=MARKER+'\n'+''.join(lines[:node.lineno-1])+block.rstrip()+'\n'+''.join(lines[node.end_lineno:])
    compile(updated,str(path),'exec')
    path.write_text(updated,encoding='utf-8')
    print('ROSTER BOUNDED DISCOVERY READY: 8s navigation; up to four 1.8s frame checks; no deep scanners',flush=True)

if __name__=='__main__':
    apply(Path(sys.argv[1]))
