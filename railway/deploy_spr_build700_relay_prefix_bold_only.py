#!/usr/bin/env python3
"""One-time Build 700 relay typography: only 'Relayed by' is bold.
Keep crew, location, linked shift normal weight, their order and links unchanged.
Reuses verified checksum-guarded SFTP deployment; preserves RC1, PDFs, indexes.
"""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('verified_b700_relay',Path('/data/tmp/build700_relay_base.py'))
deployer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)
deployer.EXPECTED={
    'script.js':'c59794ea68dad64c',
    'index.php':'f06e9014dacbdf5e',
    'index.html':'669d4d532c672685',
}
deployer.OLD_REF='script.js?v=700-relay-name-location'
deployer.NEW_REF='script.js?v=700-relayed-by-only'
D=chr(36)
crew=D+'{esc(shift.crew)}'
shift=D+'{shiftNumberLink(shift.number,{prefix:true})}'
station=D+"{esc(shift.signOnLocation||'Not identified')}"
unknown=D+'{shiftNumberLink(relayedBy.shift,{prefix:true})}'
old='Relayed by '+crew+' <span style="font-weight:400">'+station+' '+shift+'</span>'
new='Relayed by <span style="font-weight:400">'+crew+' '+station+' '+shift+'</span>'
old_unknown='Relayed by <span style="font-weight:400">'+unknown+'</span> — Crew not identified'
new_unknown='Relayed by <span style="font-weight:400">'+unknown+' — Crew not identified</span>'
def change_js(js):
    if js.count('function renderRelayedByDetails(relayedBy)')!=1:
        raise RuntimeError('Relayed-by render function shape unexpectedly changed')
    if js.count(old)!=1 or js.count(old_unknown)!=1:
        raise RuntimeError('Live relay text differs from the verified Build 700 baseline')
    if js.count('const joinedRearRelay=Boolean(relay?.joinText&&item.entry.relayedBy);')!=1:
        raise RuntimeError('Prior join/relay correction missing')
    if 'function sprOriginalPdfMatchesIndex(' not in js or 'function scheduleRetainedSprRestore()' not in js:
        raise RuntimeError('Fast-load, source SHA or last-SPR guards missing')
    return js.replace(old,new,1).replace(old_unknown,new_unknown,1)
deployer.patch_js=change_js
deployer.main()
