#!/usr/bin/env python3
"""Read-only AST audit of the patched SPR Online Updater; print no secrets."""
import ast,re,inspect,os
p="/app/spr_online_updater.py"
data=open(p,encoding="utf8").read()
tree=ast.parse(data)
lines=data.splitlines()
names=[
 "upload_pdf","run_update","upload_cached_roster_pdf","_store_roster_fast",
 "publish_roster_manifest","sync_all_rosters_online",
 "_roster_sftp_connection","_roster_sftp_release",
 "_roster_sftp_check_url","_roster_sftp_oneoff_repair",
 "_publish_roster_manifest","_spr_upload_over_sftp",
 "run_update_rosters","_run_online_update","run_online_update",
 "_upload_pdf_to_site","_kustom_sftp_open","_kustom_sftp_pdf","_kustom_sftp_roster","_kustom_sftp_manifest"
]
print("[DUAL AUDIT] total_chars",len(data),"total_lines",len(lines),flush=True)
for n in names:
   found=[x for x in tree.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name==n]
   print("[DUAL AUDIT] FUNCTION",n,"count",len(found),flush=True)
   for x in found[-2:]:
       body="\n".join(f"{idx+1} "+lines[idx] for idx in range(x.lineno-1,min(x.end_lineno,len(lines))))
       print("[DUAL AUDIT] BODY",n,"start",x.lineno,"end",x.end_lineno,
             "\n"+body[:20000],flush=True)
for marker in ("SPR_KUSTOM_SECONDARY_MIRROR_661","SPR_DUAL_LOCAL_PUBLISH_670",
    "SPR_SFTP_BODGYBROS_ONLY_674","SPR_ROSTER_SFTP_PUBLISH_VERIFIED_20261101",
    "SPR_ROSTER_SFTP_CONNECTION_REUSE_20261101", "SPR_SCHEDULE_08_12_16_22_700"):
 print("[DUAL AUDIT] MARKER",marker,"seen",marker in data,flush=True)
for needle in ("publish_roster_manifest(","upload_cached_roster_pdf(","upload_pdf("):
    hits=[(i+1,l.strip()) for i,l in enumerate(lines) if needle in l]
    print("[DUAL AUDIT] CALLS",needle,str(hits[:70])[:6000],flush=True)
