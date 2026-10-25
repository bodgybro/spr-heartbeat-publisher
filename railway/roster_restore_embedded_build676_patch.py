#!/usr/bin/env python3
"""Build 676: restore the proven SharePoint embedded-link decoder on bounded snapshots.

Build 675 protected against an unbounded browser scanner but broke all depots
by replacing the SharePoint Quick Links decoder with a raw PDF regex. This
patch restores the original decoder on short bounded HTML snapshots, without
letting it make any unbounded browser calls. Does not alter SPR upload, SFTP,
roster storage, schedules or manifests.
"""
import ast
import sys
from pathlib import Path

MARKER = '# SPR_ROSTER_EMBEDDED_BOUNDED_676'
HELPER = r'''
# Reuse the original proven Quick Links/SharePoint URL decoder without any
# browser calls. Every HTML string is retrieved upstream with Playwright's
# explicit 1.8/2.5-second timeout, not through the old fr.content() method.
def _sharepoint_embedded_roster_items_from_html(raw_html,current_url):
    class _StaticFrame:
        def __init__(self,text):self._text=text
        def eval_on_selector_all(self,*args,**kwargs):return []
        def content(self):return self._text
    class _StaticPage:
        def __init__(self,text,url):
            self.url=url
            self.frames=[_StaticFrame(text)]
    if not isinstance(raw_html,str) or not raw_html:
        return []
    if len(raw_html)>8_000_000:
        raw_html=raw_html[:8_000_000]
    return _sharepoint_embedded_roster_items(_StaticPage(raw_html,current_url),current_url)
'''

def apply(path):
    source=path.read_text(encoding='utf-8')
    if MARKER in source:
        print('Build 676 embedded roster parser already active',flush=True)
        return
    tree=ast.parse(source)
    named={f.name:f for f in tree.body if isinstance(f,ast.FunctionDef)}
    for expected in ('sync_all_rosters_online','_sharepoint_embedded_roster_items'):
        if expected not in named:raise RuntimeError('Missing proven SharePoint decoder: '+expected)
    f=named['sync_all_rosters_online']
    lines=source.splitlines(keepends=True)
    block=''.join(lines[f.lineno-1:f.end_lineno])
    old='discovered+=_fast_roster_items_from_html(html,depot_url)'
    new='discovered+=_sharepoint_embedded_roster_items_from_html(html,depot_url)'
    if block.count(old)!=1:raise RuntimeError('Bounded HTML fallback changed; refusing unsafe edit')
    if '_sharepoint_rendered_items(page,depot_url)' in block or '_sharepoint_embedded_roster_items(page,depot_url)' in block:
        raise RuntimeError('Unbounded legacy browser scan reintroduced; refusing edit')
    block=block.replace(old,new,1)
    if '_sharepoint_embedded_roster_items_from_html(rr.text(),depot_url)' not in block:
        raise RuntimeError('Direct SharePoint JSON parser call missing')
    updated=MARKER+'\n'+''.join(lines[:f.lineno-1])+HELPER+'\n'+block.rstrip()+'\n'+''.join(lines[f.end_lineno:])
    compile(updated,str(path),'exec')
    path.write_text(updated,encoding='utf-8')
    print('ROSTER LINK DECODER RESTORED: SharePoint embedded PDF links read from bounded HTML snapshots',flush=True)

if __name__=='__main__':apply(Path(sys.argv[1]))
