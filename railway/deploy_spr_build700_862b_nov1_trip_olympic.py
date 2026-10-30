#!/usr/bin/env python3
"""Build 700, 1 Nov 862B shift timeline: show verified trip destination
Olympic Park 0526; preserve handover at Lidcombe 0519. Live frontend only.
Uses existing SFTP SHA checks/staged uploads/rollback; RC1 and indexes untouched.
"""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("b700_verified_sftp",Path("/data/tmp/b700_relay_base.py"))
deployer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)
deployer.EXPECTED={
 "script.js":"d21450e90897ea4c",
 "index.php":"70e92d9ecc3b6d39",
 "index.html":"391b4d2289c1abc8",
}
deployer.OLD_REF="script.js?v=700-run-boundary"
deployer.NEW_REF="script.js?v=700-862b-olympic-park"

HELPER=r"""
// Build 700 Nov 1: The full trip destination of 862B is Olympic Park.
// Shift 4951 ends at the Lidcombe 0519 crew relief, but Shift 4878 then
// works the SAME train to Olympic Park 0526. Never alter the relief location.
// Require the published index to confirm the exact crew/time/station handover.
function verified862BTripDestination(record){
  if(state.loadedDate!=='2026-11-01'||state.role!=='driver'||
     normaliseRun(record?.run||'')!=='862B'||normaliseRun(record?.crewShift||'')!=='4951'||
     normaliseRun(record?.relievedByShift||'')!=='4878'||
     stationName(record?.runDestination||'')!=='LIDCOMBE')return null;
  const end=minutesFromTime(normaliseTime(record.runEndTime||record.reliefTime||''));
  if(!Number.isFinite(end))return null;
  const candidates=(state.index.get('862B')||state.records.filter(x=>normaliseRun(x.run||'')==='862B')).filter(next=>{
    if(next===record||normaliseRun(next.crewShift||'')!=='4878'||
       normaliseRun(next.incomingRelieveShift||'')!=='4951'||
       stationName(next.runDestination||'')!=='OLYMPIC PARK')return false;
    const start=minutesFromTime(normaliseTime(next.runStartTime||''));
    const delta=(start-end+1440)%1440;
    if(!Number.isFinite(start)||delta>2)return false;
    const first=(next.timetableRows||[]).find(row=>row?.location)?.location||next.incomingRelieveLocation||'';
    if(stationName(first)!=='LIDCOMBE')return false;
    const arrival=normaliseTime(next.destinationTiming?.arrivalTime||next.runEndTime||'');
    const arrivalMin=minutesFromTime(arrival);
    return Number.isFinite(arrivalMin)&&((arrivalMin-start+1440)%1440)>0&&((arrivalMin-start+1440)%1440)<120;
  });
  if(candidates.length!==1)return null;
  const segment=candidates[0];
  return {location:normaliseDisplayLocation(segment.runDestination),
          time:normaliseTime(segment.destinationTiming?.arrivalTime||segment.runEndTime)};
}
"""
OLD_DEST="  const destination=semanticPlace(nameDestinationLocation)||(chain.length?(semanticFirstFormLocation||semanticPlace(chain[0].fromDuty)||semanticPlace(chain[0].formLocation)): '');"
NEW_DEST="""  // The 0519 Lidcombe endpoint belongs to the crew relief, not to the
  // published 862B trip destination. Read the verified next crew segment.
  const verifiedThroughTrip=verified862BTripDestination(r);
  const destination=verifiedThroughTrip?.location||semanticPlace(nameDestinationLocation)||(chain.length?(semanticFirstFormLocation||semanticPlace(chain[0].fromDuty)||semanticPlace(chain[0].formLocation)): '');"""
OLD_TIMED="  const timedDestination=[destination,(destinationIsOperationalFacility||hideOriginTimeAfterPrepare)?'':nameDestinationTime].filter(Boolean).join(' ');"
NEW_TIMED="  const timedDestination=[destination,(destinationIsOperationalFacility||hideOriginTimeAfterPrepare)?'':(verifiedThroughTrip?.time||nameDestinationTime)].filter(Boolean).join(' ');"
def patch_js(js):
    anchor="function renderNameDuty(item,context=null){"
    if js.count(anchor)!=1 or js.count(OLD_DEST)!=1 or js.count(OLD_TIMED)!=1:
        raise RuntimeError("Expected Run/Shift 700 timeline renderer changed; no live writes")
    for protected in ("function sprOriginalPdfMatchesIndex(","function scheduleRetainedSprRestore()",
                      "function verifiedThroughRunDestination(record)","function recoveredFormedRunOrigin(record)"):
        if protected not in js:raise RuntimeError("Working Build 700 safeguard not found: "+protected)
    return js.replace(anchor,HELPER+"\n"+anchor,1).replace(OLD_DEST,NEW_DEST,1).replace(OLD_TIMED,NEW_TIMED,1)
deployer.patch_js=patch_js
deployer.main()
