#!/usr/bin/env python3
"""Archive current roster PDFs by content-derived Sunday start, on both sites.

This hooks AFTER the unchanged dual-site, SHA-verified live roster upload.
Archives remain private and on each site's own hosting account. A failed
archive never invalidates an otherwise verified live roster publication.
"""
import ast
from pathlib import Path
import sys
MARKER="# ROSTER_FORTNIGHT_ARCHIVE_20261123_V1"
EXTENSION=r'''
# ROSTER_FORTNIGHT_ARCHIVE_20261123_V1
# Current fixed filenames remain unchanged. Private archives are named by
# the actual 14-day Sunday window printed in each PDF's roster columns.
_ROSTER_HISTORY_BASE_B="/home11/bodgybro/sps-private-assets/roster-fortnights-v1"
_ROSTER_HISTORY_BASE_K="/home10/kustomvi/sps-private-assets/roster-fortnights-v1"
_ROSTER_HISTORY_PUBLISH_ORIGINAL=upload_cached_roster_pdf

def _roster_history_fortnight(data):
    from datetime import date,timedelta
    from io import BytesIO
    import re
    from pypdf import PdfReader
    if not isinstance(data,(bytes,bytearray)) or not bytes(data).startswith(b"%PDF-"):
        raise ValueError("Not a verified roster PDF")
    reader=PdfReader(BytesIO(bytes(data)),strict=False)
    if not reader.pages:raise ValueError("Roster has no pages")
    sample=(reader.pages[0].extract_text() or "")[:120000]
    days=set()
    for match in re.finditer(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)(?!\d)",sample):
        try:
            d=date(int(match[3]),int(match[2]),int(match[1]))
            if 2025<=d.year<=2031:days.add(d)
        except ValueError:pass
    if len(days)<11:
        raise ValueError("Fewer than 11 distinct printed roster date headers")
    candidates=set()
    for d in days:
        sunday=d-timedelta(days=(d.weekday()+1)%7)
        candidates.add(sunday)
        candidates.add(sunday-timedelta(days=7))
    scores=[]
    for start in candidates:
        if start.weekday()!=6:continue
        count=sum(start<=d<=start+timedelta(days=13) for d in days)
        if count>=11:scores.append((count,start))
    if not scores:raise ValueError("No complete Sunday fortnight in roster PDF")
    scores.sort(reverse=True)
    # Never silently choose between two conflicting ranges with equally good coverage.
    if len(scores)>1 and scores[0][0]==scores[1][0]:
        raise ValueError("Ambiguous fortnight headers")
    return scores[0][1].isoformat()

def _roster_history_safe_path(cache_path):
    import re
    if not isinstance(cache_path,str):raise ValueError("Roster path missing")
    parts=cache_path.replace("\\","/").split("/")
    if len(parts)!=4:raise ValueError("Roster filename shape unexpected")
    depot,role,kind,filename=parts
    permitted_depots={"auburn","blacktown","campbelltown","central",
        "cronulla","flemington","hornsby","leppington","mortdale",
        "north-sydney","penrith","richmond","waterfall"}
    if depot not in permitted_depots or role not in ("drivers","guards") or kind not in ("daily","fortnight","period"):
        raise ValueError("Unexpected roster depot, crew or period")
    if not re.fullmatch(r"[A-Za-z0-9-]{5,45}\.pdf",filename):
        raise ValueError("Unsafe cached roster filename")
    return parts

def _roster_history_remote_copy(ssh,public,private,cache_path,start,expected_sha):
    import shlex
    parts=_roster_history_safe_path(cache_path)
    source=public.rstrip("/")+"/rosters/"+"/".join(parts)
    final=private.rstrip("/")+"/"+start+"/"+"/".join(parts)
    parent=final.rsplit("/",1)[0]
    staging=final+".stage-"+expected_sha[:16]
    quoted=[shlex.quote(x) for x in (source,final,parent,staging,expected_sha)]
    src,dst,folder,tmp,expected=quoted
    # The resulting archive is never inside public_html. The SHA of the
    # original published PDF is checked before and after local server copy.
    script=("set -eu;"+
       "test -f "+src+";"+
       "echo '"+expected_sha+"  ' "+src+" | sha256sum -c - >/dev/null;"+
       "install -d -m 700 "+folder+";"+
       "if test -s "+dst+" && echo '"+expected_sha+"  ' "+dst+" | sha256sum -c - >/dev/null 2>&1;then echo ROSTER_ARCHIVE_UNCHANGED;"+
       "else cp -- "+src+" "+tmp+";chmod 600 "+tmp+";"+
       "echo '"+expected_sha+"  ' "+tmp+" | sha256sum -c - >/dev/null;"+
       "mv -f "+tmp+" "+dst+";echo ROSTER_ARCHIVE_SAVED;fi")
    stdin,stdout,stderr=ssh.exec_command(script,timeout=45)
    stdout.channel.settimeout(120)
    output=stdout.read(300).decode("ascii","replace")
    code=stdout.channel.recv_exit_status()
    stdin.close();stdout.close();stderr.close()
    if code or not ("ROSTER_ARCHIVE_SAVED" in output or "ROSTER_ARCHIVE_UNCHANGED" in output):
        raise RuntimeError("Remote private roster archival verification failed")
    return "unchanged" if "ROSTER_ARCHIVE_UNCHANGED" in output else "saved"

def _roster_history_archive_verified(cache_path,data):
    import hashlib
    parts=_roster_history_safe_path(cache_path)
    start=_roster_history_fortnight(data)
    digest=hashlib.sha256(bytes(data)).hexdigest()
    results={}
    for site in ("bodgybros","kustomvinyls"):
        ssh=ftp=None
        try:
            if site=="bodgybros":
                ssh,ftp,public=_spr_direct_primary_sftp()
                private=_ROSTER_HISTORY_BASE_B
            else:
                ssh,ftp=_dual_kustom_open()
                public=_DUAL_KUSTOM_ROOT
                private=_ROSTER_HISTORY_BASE_K
            results[site]=_roster_history_remote_copy(
                ssh,public,private,cache_path,start,digest)
        finally:
            if ftp is not None:
                try:ftp.close()
                except Exception:pass
            if ssh is not None:
                try:ssh.close()
                except Exception:pass
    print("  [ROSTER FORTNIGHT ARCHIVED] "+start+" "+"/".join(parts)+
          " bodgy="+results.get("bodgybros","pending")+
          " kustom="+results.get("kustomvinyls","pending"),flush=True)

def upload_cached_roster_pdf(url,name,data,cache_path=""):
    result=_ROSTER_HISTORY_PUBLISH_ORIGINAL(url,name,data,cache_path)
    if isinstance(data,(bytes,bytearray)) and bytes(data).startswith(b"%PDF-"):
        try:_roster_history_archive_verified(cache_path,data)
        except Exception as exc:
            # Never cause a verified live roster upload or manifest to fail.
            print("  [ROSTER FORTNIGHT ARCHIVE DEFERRED] "+
                  str(cache_path)[:90]+" "+type(exc).__name__,flush=True)
    return result
'''
def apply(path:Path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:
        print("ROSTER_FORTNIGHT_ARCHIVER_ALREADY_PATCHED")
        return
    tree=ast.parse(source)
    names={x.name for x in tree.body if isinstance(x,ast.FunctionDef)}
    expected={"upload_cached_roster_pdf","_roster_valid_cache_path","_spr_direct_primary_sftp","_dual_kustom_open"}
    if not expected.issubset(names):
        raise RuntimeError("Verified dual-site roster/SFTP pipeline absent: "+str(sorted(expected-names)))
    if "# DUAL_SITE_SFTP" not in source and "# DUAL" not in source:
        raise RuntimeError("Verified dual-site patch marker absent")
    mains=[x for x in tree.body if isinstance(x,ast.If) and
           "__name__" in (ast.get_source_segment(source,x.test) or "")]
    if not mains:raise RuntimeError("No safe updater entrypoint")
    rows=source.splitlines(keepends=True)
    index=mains[-1].lineno-1
    updated="".join(rows[:index])+EXTENSION+"\n"+"".join(rows[index:])
    ast.parse(updated);compile(updated,str(path),"exec")
    path.write_text(updated,encoding="utf-8")
    print("ROSTER_FORTNIGHT_ARCHIVER_PREPARED private_per_site=yes existing_upload_intact=yes")
if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: patch.py updater.py")
    apply(Path(sys.argv[1]))
