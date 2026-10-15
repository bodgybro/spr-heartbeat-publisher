#!/usr/bin/env python3
"""Accurate success accounting for SPR + TCREW roster uploads.
Applied after Cloudflare, roster fallback, SFTP and schedule patches.
"""
from pathlib import Path
import ast
import sys

def replace_func(s,name,edit):
    tree=ast.parse(s)
    matching=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
    if len(matching)!=1:
        raise RuntimeError("Expected one function: "+name)
    node=matching[0]
    lines=s.splitlines(keepends=True)
    block="".join(lines[node.lineno-1:node.end_lineno])
    replaced=edit(block)
    return "".join(lines[:node.lineno-1])+replaced.rstrip()+"\n"+"".join(lines[node.end_lineno:])

def swap(s,old,new):
    if s.count(old)!=1:
        raise RuntimeError("Unexpected patch target "+repr(old[:85])+" count "+str(s.count(old)))
    return s.replace(old,new,1)

def patch_update(block):
    block=swap(block,"                uploaded=[]\n                skipped=[]",
               "                uploaded=[]\n                downloaded=[]\n                skipped=[]")
    block=swap(block,'                        print(f"  [DOWNLOADED] {role}: {exact_name} ({size_mb:.1f} MB)",flush=True)',
               '                        print(f"  [DOWNLOADED] {role}: {exact_name} ({size_mb:.1f} MB)",flush=True)\n                        downloaded.append(exact_name)')
    block=swap(block,'                    results.append({"role":role,"message":err})',
               '                    results.append({"role":role,"message":err,"ok":False,"files_expected":0,"files_downloaded":0,"files_uploaded":0,"files_failed":1})')
    old='                results.append({"role":role,"message":"; ".join(parts) if parts else "No eligible files found."})'
    new='''                expected=len(targets)
                ok=bool(expected and not skipped and not errors and len(uploaded)==expected)
                summary=f"{len(uploaded)}/{expected} PDFs uploaded ({len(downloaded)} downloaded)"
                if not expected:
                    summary+="; no eligible dated folders found"
                message=summary+("; "+"; ".join(parts) if parts else "")
                print(f"  [{('COMPLETE' if ok else 'INCOMPLETE')}] {role}: {message}", flush=True)
                results.append({"role":role,"message":message,"ok":ok,
                    "files_expected":expected,"files_downloaded":len(downloaded),
                    "files_uploaded":len(uploaded),"files_failed":len(skipped)+len(errors)+(1 if not expected else 0)})'''
    block=swap(block,old,new)
    block=swap(block,'                results.append({"role":role,"message":"ERROR: "+str(e)})',
               '                results.append({"role":role,"message":"ERROR: "+str(e),"ok":False,"files_expected":0,"files_downloaded":0,"files_uploaded":0,"files_failed":1})')
    block=swap(block,'    spr_ok = all("ERROR:" not in str(x.get("message","")) for x in results if isinstance(x,dict))',
               '    spr_results=[x for x in results if isinstance(x,dict) and x.get("role") in ("Drivers","Guards")]\n    spr_ok = len(spr_results)==2 and all(x.get("ok") is True for x in spr_results)')
    block=swap(block,'            if "ERROR:" not in str(roster_result.get("message","")):',
               '            if roster_result.get("ok") is True:')
    return block

def patch_rosters(block):
    block=swap(block,'    publish_roster_manifest(root,entries)',
               '''    # Retain the existing complete roster index if any PDF failed.
    expected=len(depots)*len(roles)*len(periods)
    all_ok=bool(expected and not errors and pdf_count==expected)
    if all_ok:
        publish_roster_manifest(root,entries)
    else:
        print("TCREW roster manifest retained: not all PDFs transferred",flush=True)''')
    block=swap(block,'    msg=f"persistent roster store refreshed: {len(depots)} depots, {pdf_count} PDFs"',
               '    msg=f"{pdf_count}/{expected} roster PDFs downloaded and stored across {len(depots)} depots"')
    block=swap(block,'    return {"role":"Rosters","message":msg}',
               '''    print(f"  [{('COMPLETE' if all_ok else 'INCOMPLETE')}] Rosters: {pdf_count}/{expected} PDFs stored",flush=True)
    if all_ok:
        _record_online_success("rosters")
    return {"role":"Rosters","message":msg,"ok":all_ok,"files_expected":expected,
            "files_downloaded":pdf_count,"files_uploaded":pdf_count,
            "files_failed":max(expected-pdf_count,len(errors))}''')
    return block

def patch_worker(block):
    return swap(block,
'''            with JOB_LOCK:
                JOB.update({"running":False,"done":True,"results":result,"error":None})''',
'''            incomplete=[x for x in result if not isinstance(x,dict) or x.get("ok") is not True]
            if not result or incomplete:
                summary=" | ".join(
                    f"{x.get('role','Unknown')}: {x.get('message','No successful transfer')}"
                    if isinstance(x,dict) else str(x)
                    for x in incomplete)[:2000]
                err="Update incomplete — "+(summary or "No completed PDF transfers")
                print("[UPDATE INCOMPLETE] "+err,flush=True)
            else:
                err=None
                print("[UPDATE COMPLETE] All required PDFs downloaded and uploaded",flush=True)
            with JOB_LOCK:
                JOB.update({"running":False,"done":True,"results":result,"error":err})''')

def main(path):
    s=path.read_text(encoding="utf-8")
    if "# SPR_VERIFIED_COMPLETION_REPORTING" in s:
        print("Verified completion reporting already applied")
        return
    s=replace_func(s,"run_update",patch_update)
    s=replace_func(s,"sync_all_rosters_online",patch_rosters)
    s=replace_func(s,"start_background_update",patch_worker)
    s="# SPR_VERIFIED_COMPLETION_REPORTING\n"+s
    compile(s,str(path),"exec")
    path.write_text(s,encoding="utf-8")
    print("SPR/rosters now report incomplete when any PDF download/upload fails; manifest preserved")

if __name__=="__main__":
    main(Path(sys.argv[1]))
