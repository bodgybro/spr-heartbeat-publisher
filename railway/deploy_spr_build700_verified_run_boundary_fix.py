#!/usr/bin/env python3
"""Build 700: correct verified 29 Oct Run 623M Waterfall and 615N Cronulla display.
Uses unchanged, checksum-guarded SFTP atomic installer. No PDF/index changes.
"""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('verified_b700_relay',Path('/data/tmp/build700_relay_base.py'))
deployer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)
deployer.EXPECTED={
    'script.js':'b4aae3b18851212b',
    'index.php':'de1decc01dc9bf1b',
    'index.html':'5b4e22ecfb69ad7a'
}
deployer.OLD_REF='script.js?v=700-formed-origin'
deployer.NEW_REF='script.js?v=700-run-boundary'

CONTINUATION_HELPER=r"""
// A single run number can cross a crew handover without ending the train's
// journey. Join only verified consecutive crew segments of THAT SAME run,
// when the next crew explicitly relieved this crew at the shared station.
// Shift 805 -> 740, 615N: Central ESR 1758/1759, destination Cronulla 1847.
function verifiedThroughRunDestination(record){
  const run=normaliseRun(record?.run||'');
  const shift=normaliseRun(record?.crewShift||'');
  const end=normaliseTime(record?.runEndTime||'');
  const currentEnd=normaliseDisplayLocation(record?.runDestination||record?.destinationTiming?.destinationLocation||'');
  const endMinutes=minutesFromTime(end);
  if(!run||!shift||!currentEnd||!Number.isFinite(endMinutes))return '';
  const confirmed=(state.records||[]).filter(next=>{
    if(next===record||normaliseRun(next.run)!==run||
        normaliseRun(next.crewShift||'')===shift||
        normaliseRun(next.incomingRelieveShift||'')!==shift)return false;
    const start=minutesFromTime(normaliseTime(next.runStartTime||''));
    const delta=(start-endMinutes+1440)%1440;
    if(!Number.isFinite(start)||delta>5)return false;
    const first=(next.timetableRows||[]).find(row=>row?.location);
    if(!first||stationName(first.location)!==stationName(currentEnd))return false;
    const candidateDestination=normaliseDisplayLocation(next.runDestination||next.destinationTiming?.destinationLocation||'');
    if(!candidateDestination||/^not identified$/i.test(candidateDestination)||
       stationName(candidateDestination)===stationName(currentEnd))return false;
    const nextEnd=minutesFromTime(normaliseTime(next.runEndTime||''));
    return Number.isFinite(nextEnd)&&(nextEnd-start+1440)%1440>0;
  });
  return confirmed.length===1?normaliseDisplayLocation(confirmed[0].runDestination||confirmed[0].destinationTiming?.destinationLocation||''):'';
}
"""
OLD_DEST="  const destination=normaliseDisplayLocation(r.runDestination||(chain.length?dutyLocation(chain[0].fromDuty):''));"
NEW_DEST="  const destination=normaliseDisplayLocation(verifiedThroughRunDestination(r)||r.runDestination||(chain.length?dutyLocation(chain[0].fromDuty):''));"
OLD_BEFORE="  const dutyDetails=approach"
NEW_BEFORE=r"""  // A missing incoming relief location is NOT a valid place. Never let
  // "Not identified" override a verified originTiming.location. Run 623M:
  // the published 29/10 index has Waterfall 1630, but a missing Shift 981
  // incoming relief location previously masked it.
  if(r.incomingRelieveShift&&/^not identified$/i.test(String(r.incomingRelieveLocation||'').trim())&&parsedOrigin)
    crewOrigin=parsedOrigin;
  const dutyDetails=approach"""
def patch_js(js):
    if js.count('function renderCard(r){')!=1 or js.count(OLD_DEST)!=1 or js.count(OLD_BEFORE)!=1:
        raise RuntimeError('Live run search card formatter differs from expected Build 700')
    if js.count('  let crewOrigin=r.incomingRelieveShift&&r.incomingRelieveLocation')!=1:
        raise RuntimeError('Existing formed-origin guard missing or changed')
    if 'function sprOriginalPdfMatchesIndex(' not in js or 'function scheduleRetainedSprRestore()' not in js:
        raise RuntimeError('Working PDF SHA/fast index/last-loaded-SPR functions missing')
    if 'function recoveredFormedRunOrigin(record)' not in js:
        raise RuntimeError('Previously deployed formed-origin lookup missing')
    return js.replace('function renderCard(r){',CONTINUATION_HELPER+'\nfunction renderCard(r){',1).replace(OLD_DEST,NEW_DEST,1).replace(OLD_BEFORE,NEW_BEFORE,1)
deployer.patch_js=patch_js
deployer.main()
