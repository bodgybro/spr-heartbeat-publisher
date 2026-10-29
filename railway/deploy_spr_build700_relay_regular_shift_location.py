#!/usr/bin/env python3
"""One-time Build 700 relayed-by typography through tested SFTP transaction."""
import importlib.util
from pathlib import Path
module=Path('/data/tmp/build700_relay_base.py')
spec=importlib.util.spec_from_file_location('verified_b700_relay',module)
deployer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)
deployer.EXPECTED={
    'script.js':'6d04243fe84c7cd5',
    'index.php':'826103a4c2a2a72a',
    'index.html':'5343e1166347c775',
}
deployer.OLD_REF='script.js?v=700-relay-location'
deployer.NEW_REF='script.js?v=700-relay-normal'
D=chr(36)
crew=D+'{esc(shift.crew)}'
shift=D+'{shiftNumberLink(shift.number,{prefix:true})}'
station=D+"{esc(shift.signOnLocation||'Not identified')}"
unknown=D+'{shiftNumberLink(relayedBy.shift,{prefix:true})}'
old='Relayed by '+crew+' '+shift+' '+station
new='Relayed by '+crew+' <span style="font-weight:400">'+shift+' '+station+'</span>'
old_unknown='Relayed by '+unknown+' — Crew not identified'
new_unknown='Relayed by <span style="font-weight:400">'+unknown+'</span> — Crew not identified'
def change_js(js):
    if js.count('function renderRelayedByDetails(relayedBy)')!=1:
        raise RuntimeError('Expected one relayed-by renderer')
    if js.count(old)!=1 or js.count(old_unknown)!=1:
        raise RuntimeError('Live relayed-by markup differs; refusing update')
    if js.count('const joinedRearRelay=Boolean(relay?.joinText&&item.entry.relayedBy);')!=1:
        raise RuntimeError('Expected working PASS/relay code missing')
    return js.replace(old,new,1).replace(old_unknown,new_unknown,1)
deployer.patch_js=change_js
deployer.main()
