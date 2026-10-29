#!/usr/bin/env python3
"""One-time Build 700 origin-location display repair for runs formed from preceding duties.
Specifically correct 29 Oct Shift 805 Run 623M: Waterfall 1630.
Use proven, checksum-guarded SFTP uploader; NEVER overwrite PDFs/indexes/RC1.
"""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('verified_b700_relay',Path('/data/tmp/build700_relay_base.py'))
deployer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)
deployer.EXPECTED={
 'script.js':'3021ca46d1144d66',
 'index.php':'377214059ab11afd',
 'index.html':'526260f79310212d',
}
deployer.OLD_REF='script.js?v=700-relayed-by-only'
deployer.NEW_REF='script.js?v=700-formed-origin'

HELPER=r"""
// Build 700: A formed run may have a timetable departure time but no location
// in its own parsed record. Resolve the preceding run's verified Forms duty,
// rather than displaying "Not identified 1630" (29/10 Shift 805 Run 623M).
// This is display-only: retained and published indexes are not rewritten.
function recoveredFormedRunOrigin(record){
  const run=normaliseRun(record.run||'');
  const shift=normaliseRun(record.crewShift||'');
  if(!run||!shift)return '';
  const departure=normaliseTime(record.runStartTime||record.originTiming?.departureTime||'');
  let best=null;
  for(const previous of state.records||[]){
    if(previous===record||normaliseRun(previous.crewShift||'')!==shift||
       (Number.isFinite(previous._index)&&Number.isFinite(record._index)&&previous._index>=record._index))continue;
    const forms=[...(previous.formsChain||[])];
    if(previous.formsRun&&!forms.some(item=>normaliseRun(item.run||'')===normaliseRun(previous.formsRun))){
      forms.push({run:previous.formsRun,formLocation:dutyLocation(previous.formsFromDuty||previous.formsDuty||''),
        departureTime:normaliseTime(previous.formsFromDuty||previous.formsDuty||'')});
    }
    for(const item of forms){
      if(normaliseRun(item.run||'')!==run)continue;
      const time=normaliseTime(item.departureTime||item.fromDuty||item.duty||'');
      if(departure&&time&&departure!==time)continue;
      const location=semanticPlace(item.formLocation||item.fromDuty||item.duty||'');
      if(!location||/^not identified$/i.test(location))continue;
      if(!best||(Number.isFinite(previous._index)&&previous._index>best.index))
        best={location,time:departure||time,index:previous._index??-1};
    }
  }
  if(best)return formatTimedLocation(best.location,[],best.time);

  // Some published indexes have no predecessor transition because PDF.js
  // separated the Forms line from its source timetable. Recover it only from
  // this run's own original-page lines, same column and matching run/time.
  for(const page of state.pages||[]){
    if(Number(page.pageNo)!==Number(record.page)||!Array.isArray(page.lines))continue;
    const lines=page.lines;
    for(let i=0;i<lines.length;i++){
      const line=lines[i],text=semanticText(line.text||'');
      if(!/\bforms\b/i.test(text)||formsRunFromText(text)!==run)continue;
      const time=normaliseTime(text.match(/\bforms\s+([0-2]\d[0-5]\d)\b/i)?.[1]||'');
      if(departure&&time&&departure!==time)continue;
      const rows=extractTimetableRows(lines,Math.max(-1,i-70),i,line.column);
      const last=rows.at(-1);
      const location=last?semanticPlace(last.location||''):'';
      if(!location||/^not identified$/i.test(location))continue;
      const rowTimes=last?rowDisplayTimes(last).map(normaliseTime):[];
      if(time&&rowTimes.length&&!rowTimes.includes(time))continue;
      return formatTimedLocation(location,[],departure||time);
    }
  }
  return '';
}
"""
OLD=r"""  const crewOrigin=r.incomingRelieveShift&&r.incomingRelieveLocation
    ?formatTimedLocation(r.incomingRelieveLocation,r.originTiming?.times||[],r.originTiming?.departureTime||'')
    :parsedOrigin;"""
NEW=r"""  let crewOrigin=r.incomingRelieveShift&&r.incomingRelieveLocation
    ?formatTimedLocation(r.incomingRelieveLocation,r.originTiming?.times||[],r.originTiming?.departureTime||'')
    :parsedOrigin;
  // Only repair missing locations. A genuinely known run origin or relief
  // point keeps its existing displayed value and ordering.
  if(!r.incomingRelieveShift&&(!crewOrigin||/^not identified(?:\s+\d{4})?$/i.test(crewOrigin))){
    const formedOrigin=recoveredFormedRunOrigin(r);
    if(formedOrigin)crewOrigin=formedOrigin;
  }"""
def patch_js(js):
    if js.count('function renderCard(r){')!=1 or js.count(OLD)!=1:
        raise RuntimeError('Expected Build 700 Run renderer missing; no changes')
    if 'function sprOriginalPdfMatchesIndex(' not in js or 'function scheduleRetainedSprRestore()' not in js:
        raise RuntimeError('Existing PDF checksum/last-SPR code missing')
    if js.count('const joinedRearRelay=Boolean(relay?.joinText&&item.entry.relayedBy);')!=1:
        raise RuntimeError('Existing Shift 2871 PASS correction missing')
    return js.replace('function renderCard(r){',HELPER+'\nfunction renderCard(r){',1).replace(OLD,NEW,1)
deployer.patch_js=patch_js
deployer.main()
