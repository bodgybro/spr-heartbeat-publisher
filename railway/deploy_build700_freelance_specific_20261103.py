#!/usr/bin/env python3
"""Deploy the 3 Nov 2026 Build700 Freelance Specific fix to both independent sites.

Read current site code via authenticated, pinned SSH, change only one search
branch, Node syntax check, SHA verify staged/published JS & HTML on each host.
Rollback changed files if either publication fails. No PDFs/rosters are changed.
"""
import os,io,base64,hashlib,shlex,posixpath,subprocess,tempfile
import paramiko
OLD="script-700-fromto-locations-v1.js"
NEW="script-700-freelance-specific-v1.js"
MARKER="// ROSTER_FREELANCE_SPECIFIC_20261103"
INJECT="\n// ROSTER_FREELANCE_SPECIFIC_20261103\n// Freelance Cross Sector is the same Specific category as plain Freelance.\n// The existing active-shift crew selector isolates unstruck, separate names.\nfunction rosterFreelanceTime(text){\n  const m=String(text||'').match(/(?:^|[^\\d])(\\d{1,2}):(\\d{2})\\s*[-–—]\\s*(\\d{1,2}):(\\d{2})(?=$|[^\\d])/);\n  if(!m)return '';\n  const pad=n=>String(n).padStart(2,'0');\n  return pad(m[1])+m[2]+'-'+pad(m[3])+m[4];\n}\nfunction rosterFreelanceDate(label){\n  const date=rosterSpecificDateDisplay(label);\n  const m=date.label.match(/^(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})$/);\n  return {...date,short:m?(Number(m[1])+'/'+Number(m[2])+'/'+m[3].slice(-2)):date.label};\n}\nfunction rosterFreelancePerson(active){\n  let raw=rosterCleanSpecificCrewDisplay((active&&active.raw)||'');\n  if(raw){\n    raw=rosterKeepFirstCrewPerson(raw);\n    const i=raw.indexOf(',');\n    if(i>0){\n      const surname=raw.slice(0,i).trim(),given=raw.slice(i+1).trim();\n      if(surname&&given)return (given+' '+surname).replace(/\\s+/g,' ').trim();\n    }\n  }\n  const crew=rosterCleanSpecificCrewDisplay((active&&active.crew)||'');\n  return (crew||raw).replace(/,/g,' ').replace(/\\s+/g,' ').trim();\n}\nasync function rosterSearchFreelance(){\n  const selectedDate=rosterAdvancedUi.specificDate.value;\n  rosterUi.results.replaceChildren();\n  rosterSetStatus('Searching Freelance roster duties…');\n  const renderCache=new Map(),groups=new Map();\n  for(const page of rosterState.pages){\n    const cols=selectedDate?[rosterSelectedDateColumn(page,selectedDate)].filter(Boolean):rosterDateColumns(page);\n    if(!cols.length)continue;\n    for(const row of rosterRowAnchors(page)){\n      const matches=[];\n      for(const col of cols){\n        // Use the proven left-anchored PDF text ownership, not the text\n        // box centre; long \"Freelance Cross Sector\" items span cell edges.\n        const cell=rosterCellText(page,row.y,col);\n        if(!/\\bFreelance\\b/i.test(cell))continue;\n        matches.push({date:rosterFreelanceDate(col.label),time:rosterFreelanceTime(cell)});\n      }\n      if(!matches.length)continue;\n      const line=rosterLineNumberForRow(page,row.y);\n      if(!line)continue;\n      let active={crew:'',raw:''};\n      try{\n        active=await rosterActiveShiftCrewForRow(rosterState.pdfDoc,page,row.y,renderCache);\n      }catch(error){console.warn('[Freelance active crew]',error);}\n      let crew=rosterFreelancePerson(active);\n      if(!crew){\n        // Rare non-comma rows: preserve the original strike-through guard.\n        if(await rosterCrewStruck(page,row.y,renderCache))continue;\n        const fallback=rosterKeepFirstCrewPerson(\n          rosterCleanSpecificCrewDisplay(rosterCrewNameForExactRow(page,row.y)));\n        crew=rosterFreelancePerson({raw:fallback,crew:fallback});\n      }\n      if(!crew||!/[A-Za-z]/.test(crew))continue;\n      const key=line+'|'+crew.toLocaleLowerCase();\n      let result=groups.get(key);\n      if(!result){\n        result={line,crew,dates:new Map()};\n        groups.set(key,result);\n      }\n      for(const item of matches)result.dates.set(item.date.key,item);\n    }\n  }\n  const results=[...groups.values()].sort((a,b)=>Number(a.line)-Number(b.line)||a.crew.localeCompare(b.crew));\n  for(const result of results){\n    const dates=[...result.dates.values()].sort((a,b)=>a.date.key.localeCompare(b.date.key));\n    if(selectedDate){\n      for(const item of dates)\n        rosterTextCard(result.crew+(item.time?' '+item.time:'')+' Line '+result.line+' '+item.date.short);\n    }else{\n      const labels=dates.map(item=>item.date.short+(item.time?' '+item.time:''));\n      rosterTextCard(result.crew+' Freelance - Line '+result.line+' - Dates: '+labels.join(', '));\n    }\n  }\n  if(!results.length)rosterTextCard('No Freelance roster lines found.');\n  const days=new Set(results.flatMap(item=>[...item.dates.keys()])).size;\n  rosterSetStatus(results.length+' matching Freelance roster line'+(results.length===1?'':'s')+\n    ' found'+(!selectedDate&&results.length?' across '+days+' date'+(days===1?'':'s'):'')+'.');\n}\n"
def say(*s):print("[FREELANCE FIX]",*s,flush=True)
def sha(b):return hashlib.sha256(b).hexdigest()
def source_key():
 raw=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode()
 for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
  try:return cls.from_private_key(io.StringIO(raw))
  except Exception:pass
 raise RuntimeError("Source SSH key missing")
def make(host,user,key,known,port):
 cli=paramiko.SSHClient()
 cli.load_host_keys(known)
 cli.set_missing_host_key_policy(paramiko.RejectPolicy())
 cli.connect(hostname=host,username=user,pkey=key,port=port,timeout=15,
             auth_timeout=15,banner_timeout=15,look_for_keys=False,allow_agent=False)
 cli.get_transport().set_keepalive(20)
 return cli
def root_source():
 root=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
 if root.endswith("/sps/spr"):root=root[:-4]
 elif root.endswith("/public_html"):root+="/sps"
 if not root.endswith("/sps"):raise RuntimeError("Unexpected source root")
 return root
def remote_sha(client,path):
 inp,out,err=client.exec_command("sha256sum -- "+shlex.quote(path),timeout=20)
 out.channel.settimeout(40)
 text=out.read(180).decode("ascii",errors="replace")
 rc=out.channel.recv_exit_status()
 inp.close();out.close();err.close()
 if rc or len(text)<64 or any(c not in "0123456789abcdef" for c in text[:64]):
  raise RuntimeError("Cannot verify remote SHA")
 return text[:64]
def read(ftp,root,name):
 with ftp.open(posixpath.join(root,name),"rb") as stream:
  stream.prefetch(max_concurrent_requests=24)
  return stream.read()
def patch_js(src):
 s=src.decode("utf-8")
 sig="async function rosterSearchSpecific(){\n  const term=rosterAdvancedUi.specificType.value;"
 if s.count(sig)!=1 or MARKER in s:
  raise RuntimeError("Versioned roster search source unexpected")
 for f in ("rosterActiveShiftCrewForRow","rosterCellText","rosterKeepFirstCrewPerson",
           "rosterSpecificDateDisplay","rosterCrewStruck"):
  if "function "+f+"(" not in s and "async function "+f+"(" not in s:
   raise RuntimeError("Required original crew parser helper missing: "+f)
 revised=s.replace(sig,INJECT+"\n"+sig+
   "\n  if(/^Freelance$/i.test(term))return rosterSearchFreelance();",1)
 if revised.count(MARKER)!=1:raise RuntimeError("Patch marker not unique")
 b=revised.encode("utf-8")
 with tempfile.NamedTemporaryFile(suffix=".js",delete=False) as f:
  f.write(b); tmp=f.name
 try:
  check=subprocess.run(["node","--check",tmp],capture_output=True,text=True,timeout=20)
  if check.returncode:raise RuntimeError("JavaScript syntax failed: "+check.stderr[:280])
 finally:os.unlink(tmp)
 return b
def inspect(label,client,root):
 ftp=client.open_sftp()
 try:
  originals={n:read(ftp,root,n) for n in (OLD,"script.js","index.php","index.html")}
  for name in ("index.php","index.html"):
   if originals[name].count(OLD.encode())!=1:
    raise RuntimeError(label+" doesn't import expected module: "+name)
  updated_js=patch_js(originals[OLD])
  updated={NEW:updated_js,"script.js":updated_js}
  for name in ("index.php","index.html"):
   updated[name]=originals[name].replace(OLD.encode(),NEW.encode(),1)
  for name,data in originals.items():
   if remote_sha(client,posixpath.join(root,name))!=sha(data):
    raise RuntimeError(label+" changed during source inspection: "+name)
  try:
   st=ftp.stat(posixpath.join(root,NEW))
   if st.st_size!=len(updated_js) or remote_sha(client,posixpath.join(root,NEW))!=sha(updated_js):
    raise RuntimeError(label+" versioned module name collision")
  except FileNotFoundError:pass
  say("PREFLIGHT",label,"original",sha(originals[OLD])[:16],"new",sha(updated_js)[:16])
  return {"label":label,"client":client,"ftp":ftp,"root":root,
          "originals":originals,"updated":updated,"changed":[]}
 except Exception:
  ftp.close();raise
def write(site,name,data,record=True):
 remote=posixpath.join(site["root"],name)
 temp=remote+".freelance-staged-"+str(os.getpid())
 try:
  with site["ftp"].open(temp,"wb") as stream:
   stream.set_pipelined(True)
   for i in range(0,len(data),1024*1024):stream.write(data[i:i+1024*1024])
  site["ftp"].chmod(temp,0o644)
  if site["ftp"].stat(temp).st_size!=len(data) or remote_sha(site["client"],temp)!=sha(data):
   raise RuntimeError("Staged hash mismatch "+site["label"]+"/"+name)
  site["ftp"].posix_rename(temp,remote)
  if remote_sha(site["client"],remote)!=sha(data):
   raise RuntimeError("Published hash mismatch "+site["label"]+"/"+name)
  if record:site["changed"].append(name)
  say("LIVE SHA VERIFIED",site["label"],name,sha(data)[:16])
 finally:
  try:site["ftp"].remove(temp)
  except OSError:pass
def rollback(site):
 for name in reversed(site["changed"]):
  try:
   if name==NEW:site["ftp"].remove(posixpath.join(site["root"],name))
   else:write(site,name,site["originals"][name],record=False)
   say("RESTORED",site["label"],name)
  except Exception as exc:say("RESTORE FAILED",site["label"],name,str(exc)[:80])
 site["changed"].clear()
def main():
 c1=make(os.environ["SFTP_HOST"],os.environ["SFTP_USERNAME"],source_key(),
         "/data/credentials/spr-sftp-known_hosts",int(os.environ.get("SFTP_PORT") or 22))
 c2=make("cp-wc18.per01.ds.network","kustomvi",
         paramiko.Ed25519Key.from_private_key_file("/data/credentials/kustom-transfer/id_ed25519"),
         "/data/credentials/kustom-transfer/known_hosts",22)
 sites=[]
 try:
  sites=[inspect("bodgybros",c1,root_source()),
         inspect("kustomvinyls",c2,"/home10/kustomvi/public_html/sps")]
  say("PREFLIGHT OK; two independent websites, both Node syntax-valid")
  for site in sites:
   for name in (NEW,"script.js","index.php","index.html"):
    write(site,name,site["updated"][name])
  say("SUCCESS","Both websites now import",NEW,
      "Freelance cross-sector, active crew and shift time corrected; PDFs unchanged")
 except Exception:
  for site in reversed(sites):rollback(site)
  raise
 finally:
  for site in sites:
   try:site["ftp"].close()
   except Exception:pass
  c1.close();c2.close()
if __name__=="__main__":
 try:main()
 except Exception as exc:
  say("FAILED",type(exc).__name__,str(exc)[:270])
  raise
