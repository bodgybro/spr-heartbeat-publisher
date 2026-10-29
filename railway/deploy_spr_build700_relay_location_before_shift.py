#!/usr/bin/env python3
"""One-time Build 700 relay field order: crew, sign-on location, Shift link.
Keep crew bold, location + shift regular; use tested SHA-guarded SFTP deployer.
No changes to SPR files, rosters, updater, PDF viewer, cache or RC1.
"""
import importlib.util
from pathlib import Path
source=Path('/data/tmp/build700_relay_base.py')
spec=importlib.util.spec_from_file_location('verified_b700_relay',source)
deployer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)
deployer.EXPECTED={
    'script.js':'5ac28929f441d260',
    'index.php':'4c3a834cb40ee34d',
    'index.html':'32733f7b9bc314ca',
}
deployer.OLD_REF='script.js?v=700-relay-normal'
deployer.NEW_REF='script.js?v=700-relay-name-location'
D=chr(36)
crew=D+'{esc(shift.crew)}'
shift=D+'{shiftNumberLink(shift.number,{prefix:true})}'
station=D+"{esc(shift.signOnLocation||'Not identified')}"
old='Relayed by '+crew+' <span style="font-weight:400">'+shift+' '+station+'</span>'
new='Relayed by '+crew+' <span style="font-weight:400">'+station+' '+shift+'</span>'
def patch_js(js):
    if js.count(old)!=1 or js.count('function renderRelayedByDetails(relayedBy)')!=1:
        raise RuntimeError('Expected live relay typography missing; no changes made')
    if js.count('const joinedRearRelay=Boolean(relay?.joinText&&item.entry.relayedBy);')!=1:
        raise RuntimeError('Working PASS/relay block missing')
    if 'function sprOriginalPdfMatchesIndex(' not in js or 'function scheduleRetainedSprRestore()' not in js:
        raise RuntimeError('Working SHA/last-SPR safeguards missing')
    return js.replace(old,new,1)
deployer.patch_js=patch_js
deployer.main()
