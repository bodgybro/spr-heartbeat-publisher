#!/usr/bin/env node
/* Extract exact 14-day rows using the existing deployed reader's own
 * geometry helpers and the same pinned PDF.js version. The private reader
 * source is supplied locally and is never included in an index or log. */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import vm from 'node:vm';
import {pathToFileURL} from 'node:url';
const [readerPath,modulePath,mode,input,output,cachePath]=process.argv.slice(2);
if(!readerPath||!modulePath||!['single','batch'].includes(mode)||!input||!output)throw Error('usage: reader.js pdf.mjs single PDF JSON CACHE_PATH | batch ROSTER_DIR OUTPUT_DIR');
const source=await fs.readFile(readerPath,'utf8');
const helperNames=['rosterDateColumns','rosterStrictLineAnchors','rosterRowBounds','rosterCellItems','rosterCellText'];
// Top-level functions in the established independent reader end at column 1.
const extract=name=>{
 const m=source.match(new RegExp('^function '+name+'\\([^\\n]*\\)\\{[\\s\\S]*?^\\}','m'));
 if(!m)throw Error('Missing known reader helper: '+name);
 return m[0];
};
const norm=source.match(/^function rosterNormText\(v\)\{[^\n]*\}/m);
if(!norm)throw Error('Missing reader text normalizer');
const ctx=vm.createContext({});
vm.runInContext([norm[0],...helperNames.map(extract)].join('\n')+'\nthis.reader={'+helperNames.join(',')+'};',ctx);
const R=ctx.reader;
const pdfjs=await import(pathToFileURL(path.resolve(modulePath)).href);
if(pdfjs.version!=='4.10.38')throw Error('Unexpected PDF.js version: '+pdfjs.version);
const dateIso=s=>{
 const m=String(s||'').match(/^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{2}|\d{4})$/);
 if(!m)return null;
 const year=+m[3]+(m[3].length===2?2000:0),d=new Date(Date.UTC(year,+m[2]-1,+m[1]));
 return d.getUTCFullYear()===year&&d.getUTCMonth()+1===+m[2]&&d.getUTCDate()===+m[1]?d.toISOString().slice(0,10):null;
};
const nextDate=(s,n)=>new Date(Date.parse(s+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
async function parse(file,rel){
 if(!/^(auburn|blacktown|campbelltown|central|cronulla|flemington|hornsby|leppington|mortdale|northsydney|north-sydney|penrith|richmond|waterfall)\/(drivers|guards)\/(daily|period|fortnight)\/[A-Za-z0-9-]{5,45}\.pdf$/.test(rel))throw Error('Invalid roster cache path');
 const data=await fs.readFile(file),sha=crypto.createHash('sha256').update(data).digest('hex');
 if(data.subarray(0,5).toString()!=='%PDF-')throw Error('Invalid PDF');
 const task=pdfjs.getDocument({data:new Uint8Array(data),verbosity:0,isEvalSupported:false,useSystemFonts:false});
 const doc=await task.promise;
 const rows=new Map(),conflicts=new Set();
 try{
  for(let n=1;n<=doc.numPages;n++){
   const page=await doc.getPage(n),content=await page.getTextContent(),viewport=page.getViewport({scale:1});
   const pageInfo={pageNo:n,width:viewport.width,height:viewport.height,items:content.items.filter(i=>i.str?.trim()).map(i=>({text:i.str.trim(),x:+i.transform[4].toFixed(1),y:+i.transform[5].toFixed(1),w:+i.width.toFixed(1),h:+Math.max(5,Math.hypot(i.transform[2]||0,i.transform[3]||0)).toFixed(1)})),lines:[]};
   const cols=R.rosterDateColumns(pageInfo),dates=cols.map(c=>dateIso(c.label));
   // Partial pages, ambiguous and split-week rows remain PDF fallback only.
   if(cols.length!==14||dates.some(d=>!d)||new Set(dates).size!==14)continue;
   const start=dates[0];
   if(new Date(start+'T00:00:00Z').getUTCDay()!==0||dates.some((d,i)=>d!==nextDate(start,i)))continue;
   for(const anchor of R.rosterStrictLineAnchors(pageInfo)){
    const line=String(Number(anchor.text));
    if(!/^\d{1,4}$/.test(line))continue;
    const days=cols.map((c,i)=>({date:dates[i],cell:R.rosterCellText(pageInfo,anchor.y,c)}));
    if(days.some(d=>!d.cell||d.cell.length>500))continue;
    const key=start+'|'+line,existing=rows.get(key);
    if(existing&&JSON.stringify(existing.days)!==JSON.stringify(days))conflicts.add(key);
    rows.set(key,{start,line,days});
   }
   page.cleanup();
  }
 }finally{await doc.destroy();}
 for(const key of conflicts)rows.delete(key);
 if(!rows.size)throw Error('No complete unambiguous rows');
 return {path:rel,sha,size:data.length,rows:[...rows.values()]};
}
async function write(file,rel,dest){
 const obj=await parse(file,rel);
 await fs.writeFile(dest,JSON.stringify(obj),{mode:0o600});
 console.log('ROSTER_SQLITE_PARSED '+rel+' rows='+obj.rows.length);
}
if(mode==='single'){
 await write(input,cachePath,output);
}else{
 await fs.mkdir(output,{recursive:true,mode:0o700});
 let ok=0,review=0,files=0;
 for(const depot of await fs.readdir(input,{withFileTypes:true})){
  if(!depot.isDirectory())continue;
  for(const crew of ['drivers','guards'])for(const kind of ['daily','period','fortnight']){
   const folder=path.join(input,depot.name,crew,kind);
   let entries;try{entries=await fs.readdir(folder,{withFileTypes:true})}catch{continue}
   for(const e of entries){
    if(!e.isFile()||!/\.pdf$/i.test(e.name))continue;
    files++;
    const rel=[depot.name,crew,kind,e.name].join('/');
    try{await write(path.join(folder,e.name),rel,path.join(output,rel.replaceAll('/','__').replace(/\.pdf$/i,'.json')));ok++}
    catch(err){review++;console.log('ROSTER_SQLITE_PARSER_REVIEW '+rel+' '+err.name)}
   }
  }
 }
 console.log('ROSTER_SQLITE_SEED files='+files+' indexed='+ok+' fallback='+review);
 if(!ok)throw Error('No valid roster documents indexed');
}
