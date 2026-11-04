#!/usr/bin/env python3
"""Read-only, sanitized structure audit of running SPR updater for ROC integration.
Never logs secrets, CSV contents, SharePoint cookies, file paths under credentials.
"""
from pathlib import Path
import ast
import re
import sys

source=Path(sys.argv[1]).read_text(encoding="utf-8")
tree=ast.parse(source)
wanted=("browser","sharepoint","roster","update","scheduled","scheduler","sftp","storage","context","login","profile","run_update","status","download")
names=[(n.name,n.lineno,n.end_lineno,len(n.args.args) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) else None) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and any(k in n.name.lower() for k in wanted)]
print("[ROC AUDIT] updater source size",len(source),"functions",len([x for x in tree.body if isinstance(x,ast.FunctionDef)]),flush=True)
for name,lo,hi,argc in names[:130]:
 print(f"[ROC AUDIT] FUNCTION {name} L{lo}-{hi} params={argc}",flush=True)
for n in tree.body:
 if isinstance(n,ast.Assign):
  keys=[t.id for t in n.targets if isinstance(t,ast.Name)]
  for key in keys:
   if any(x in key.lower() for x in ("profile","data_root","context","sharepoint","run_times")):
    expression=ast.unparse(n.value)[:160]
    expression=re.sub(r"(?i)(password|token|secret|key)[^ ]*", "[REDACTED]",expression)
    print(f"[ROC AUDIT] CONSTANT {key} = {expression}",flush=True)
inspect=("sync_all_rosters_online","_wait_for_sharepoint_signin","_sharepoint_session_ready","run_update","start_background_update","auto_update_scheduler","_roster_sftp_connection")
lines=source.splitlines()
for n in tree.body:
 if isinstance(n,ast.FunctionDef) and n.name in inspect:
  print("[ROC AUDIT] EXCERPT "+n.name,flush=True)
  candidates=[]
  for i in range(n.lineno-1,min(n.end_lineno,len(lines))):
   l=lines[i]
   if any(x in l.lower() for x in ("context","browser","page=","page =","goto(","connect(","profile","launch(","launch_persistent","request.get","fetch","sync_playwright","with sync_playwright","return ","data_root","lock","thread","_wait_for_sharepoint","_sharepoint_session","schedule","run_update","sync_all","import ","save_","upload_","sftp","site_url","getenv","os.environ","if ", "except ")):
    if any(x in l.lower() for x in ("password","private_key","token","secret","cookie","credential")):continue
    candidates.append(str(i+1)+": "+l.strip()[:180])
  for part in candidates[:65]:
   print("[ROC AUDIT] "+part,flush=True)
print("[ROC AUDIT] COMPLETE",flush=True)
