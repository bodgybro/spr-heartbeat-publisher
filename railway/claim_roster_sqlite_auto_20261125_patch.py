#!/usr/bin/env python3
"""Index published roster PDFs after the existing verified private archive.
The original uploader, manifest and PDF archive are unaffected by failures.
Uses the local live reader helpers, pinned PDF.js, and SSH to each private DB.
"""
import ast,sys
from pathlib import Path
MARKER="# CLAIM_ROSTER_SQLITE_AUTO_20261125_V1"
EXTENSION=r'''
# CLAIM_ROSTER_SQLITE_AUTO_20261125_V1
def _cc_roster_sqlite_module():
    import base64,hashlib,io,json,os,tarfile,urllib.request
    from pathlib import Path
    base=Path("/data/claim-roster-index-pdfjs-4.10.38")
    module=base/"pdf.mjs"
    if module.is_file() and (base/"pdf.worker.mjs").is_file():
        return module
    base.mkdir(mode=0o700,parents=True,exist_ok=True)
    url="https://registry.npmjs.org/pdfjs-dist/4.10.38"
    with urllib.request.urlopen(url,timeout=25) as f:
        meta=json.load(f)
    assert meta["version"]=="4.10.38"
    tarurl="https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-4.10.38.tgz"
    assert meta["dist"]["tarball"]==tarurl
    with urllib.request.urlopen(tarurl,timeout=45) as f:
        raw=f.read(30000001)
    if len(raw)>30000000:raise ValueError("PDF.js distribution too large")
    expected=meta["dist"]["integrity"]
    if "sha512-"+base64.b64encode(hashlib.sha512(raw).digest()).decode()!=expected:
        raise ValueError("PDF.js distribution integrity mismatch")
    with tarfile.open(fileobj=io.BytesIO(raw),mode="r:gz") as tf:
        for filename in ("pdf.worker.mjs","pdf.mjs"):
            member=tf.getmember("package/legacy/build/"+filename)
            if not member.isfile() or member.size>15000000:raise ValueError("Invalid PDF.js member")
            temp=base/(filename+".stage")
            temp.write_bytes(tf.extractfile(member).read())
            temp.chmod(0o600);os.replace(temp,base/filename)
    return module

def _cc_roster_index_after_archive(ssh,public,private,cache_path,data,digest,payload_cache):
    import hashlib,json,os,shlex,shutil,subprocess,tempfile
    from pathlib import Path
    base=Path(private).parent/"claim-roster-index-v1"
    importer=str(base/"import.php")
    # Reuse the existing verified SSH session. Skip already indexed hashes
    # before downloading parser or decoding a PDF.
    query='$db=new SQLite3($argv[1],SQLITE3_OPEN_READONLY);$q=$db->prepare("SELECT COUNT(*) FROM documents WHERE path=:p AND sha=:s");$q->bindValue(":p",$argv[2]);$q->bindValue(":s",$argv[3]);echo $q->execute()->fetchArray(SQLITE3_NUM)[0];'
    cmd="test -f "+shlex.quote(importer)+" || exit 3; if test -s "+shlex.quote(str(base/"rosters.sqlite"))+"; then php -r "+shlex.quote(query)+" "+shlex.quote(str(base/"rosters.sqlite"))+" "+shlex.quote(cache_path)+" "+shlex.quote(digest)+"; else echo 0; fi"
    stdin,stdout,stderr=ssh.exec_command(cmd,timeout=30)
    try:
        value=stdout.read(100).decode("ascii","replace").strip()
        code=stdout.channel.recv_exit_status()
    finally:stdin.close();stdout.close();stderr.close()
    if code:raise RuntimeError("Private roster index importer unavailable")
    if value.isdigit() and int(value)>0:return "unchanged"
    reader_path=public.rstrip("/")+"/check/reader.js"
    stdin,stdout,stderr=ssh.exec_command("cat "+shlex.quote(reader_path),timeout=30)
    try:
        reader=stdout.read(3000001)
        code=stdout.channel.recv_exit_status()
    finally:stdin.close();stdout.close();stderr.close()
    if code or not reader or len(reader)>3000000:raise RuntimeError("Live roster reader unavailable")
    reader_sha=hashlib.sha256(reader).hexdigest()
    key=(digest,reader_sha,cache_path)
    if key not in payload_cache:
        node=shutil.which("node")
        if not node:
            from playwright._impl._driver import compute_driver_executable
            node=str(compute_driver_executable()[0])
        module=_cc_roster_sqlite_module()
        parser="/app/claim_roster_sqlite_exact_20261125.mjs"
        with tempfile.TemporaryDirectory(prefix="cc-roster-index-",dir="/data/tmp") as tmp:
            p=Path(tmp);(p/"reader.js").write_bytes(reader);(p/"original.pdf").write_bytes(data)
            run=subprocess.run([node,parser,str(p/"reader.js"),str(module),"single",str(p/"original.pdf"),str(p/"rows.json"),cache_path],capture_output=True,timeout=90)
            if run.returncode:raise RuntimeError("Exact roster row parser failed")
            raw=(p/"rows.json").read_bytes()
            obj=json.loads(raw)
            if obj.get("sha")!=digest or obj.get("path")!=cache_path or not obj.get("rows"):
                raise ValueError("Index payload failed source validation")
            payload_cache[key]=raw
    payload=payload_cache[key]
    stdin,stdout,stderr=ssh.exec_command("php "+shlex.quote(importer),timeout=90)
    try:
        stdin.write(payload);stdin.flush();stdin.channel.shutdown_write()
        result=stdout.read(500).decode("ascii","replace")
        code=stdout.channel.recv_exit_status()
    finally:stdin.close();stdout.close();stderr.close()
    if code or "ROSTER_SQLITE_IMPORT_PASS" not in result:raise RuntimeError("Private roster index import rejected")
    return "indexed"
'''
def apply(path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:return
    if "# ROSTER_FORTNIGHT_ARCHIVE_20261123_V1" not in source:
        raise RuntimeError("Existing verified archive hook required")
    old='    results={}\n    for site in ("bodgybros","kustomvinyls"):'
    if source.count(old)!=1:raise RuntimeError("Archive loop changed")
    source=source.replace(old,'    results={}\n    cc_payload_cache={}\n    for site in ("bodgybros","kustomvinyls"):',1)
    old='''            results[site]=_roster_history_remote_copy(
                ssh,public,private,cache_path,start,digest)'''
    if source.count(old)!=1:raise RuntimeError("Verified archive copy call changed")
    source=source.replace(old,old+'''
            try:
                cc_status=_cc_roster_index_after_archive(ssh,public,private,cache_path,data,digest,cc_payload_cache)
                print("  [ROSTER SQLITE "+cc_status.upper()+"] "+site+" "+cache_path,flush=True)
            except Exception as cc_exc:
                print("  [ROSTER SQLITE DEFERRED] "+site+" "+cache_path+" "+type(cc_exc).__name__,flush=True)''',1)
    anchor="def _roster_history_archive_verified(cache_path,data):"
    if source.count(anchor)!=1:raise RuntimeError("Archive entrypoint changed")
    source=source.replace(anchor,EXTENSION+"\n"+anchor,1)
    ast.parse(source);compile(source,str(path),"exec")
    path.write_text(source,encoding="utf-8")
    print("ROSTER_SQLITE_AUTO_HOOK_READY existing_archive_and_upload_preserved=yes",flush=True)
if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("Usage: patch.py updater.py")
    apply(Path(sys.argv[1]))
