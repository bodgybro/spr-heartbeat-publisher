#!/usr/bin/env python3
"""One-time Build 700 JOIN relay location display correction. Reuses verified SFTP deployer."""
import importlib.util
from pathlib import Path
module=Path('/data/tmp/build700_relay_base.py')
spec=importlib.util.spec_from_file_location('verified_b700_relay',module)
deployer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)
deployer.EXPECTED={
  'script.js':'3856aeed043fd7bd',
  'index.php':'cc36c20a214a91e2',
  'index.html':'b0378d3f0aa60868'}
deployer.OLD_REF='script.js?v=700-relay-pass'
deployer.NEW_REF='script.js?v=700-relay-location'
old="""?(relay.location?'<div class="secondary">Location: '+esc(relay.location)+'</div>':'')"""
new="""?(relay.location?'<div class="secondary">Location: '+esc(String(relay.location).replace(/^\\s*@\\s*/, ''))+'</div>':'')"""
def change_js(js):
    if js.count(old)!=1 or js.count('const joinedRearRelay=Boolean(relay?.joinText&&item.entry.relayedBy);')!=1:
        raise RuntimeError('JOIN relay rendering has changed, refusing modification')
    return js.replace(old,new,1)
deployer.patch_js=change_js
deployer.main()
