#!/usr/bin/env python3
"""Replace obsolete browser SPR indexing with verified Node original-PDF indexing.

This patch runs AFTER all legacy updater + two-site SFTP patches. It changes
only the indexed-PDF background consumer, not SPR downloads, PDF uploads,
rosters, user login, or the four existing update slots.

The verified JS builder is injected privately via SPR_DIRECT_INDEXER_JS_B64
and verified against SPR_DIRECT_INDEXER_JS_SHA256. The active parser comes
from the existing Bodgybros private assets. Both original source PDFs must
match the upload's SHA-256 before a dated index can be published.

The original browser-based indexer remains in the source for rollback but
is never called by the new background worker or catch-up path.
"""
from pathlib import Path
import ast
import sys

MARKER="# SPR_DIRECT_ORIGINAL_PDF_NODE_INDEXER_20261119"
EXTENSION=r'''
# SPR_DIRECT_ORIGINAL_PDF_NODE_INDEXER_20261119
# Reuse the pre-existing, verified upload -> queued date/role/SHA pipeline.
# This extension is intentionally applied after all dual-site amendments.
def _spr_direct_index_runtime():
    import base64,hashlib,os,pathlib,platform,shutil,subprocess,tarfile,urllib.request
    # Keep generated Node/pdfjs modules off the 500MB persistent /data volume.
    # They are reproducible runtime dependencies, NOT rosters or user data.
    # npm also needs its cache and temporary files on the container disk.
    home=pathlib.Path("/app/spr-direct-indexer")
    home.mkdir(parents=True,exist_ok=True)
    encoded=os.environ.get("SPR_DIRECT_INDEXER_JS_B64","").strip()
    sha=os.environ.get("SPR_DIRECT_INDEXER_JS_SHA256","").strip()
    if not encoded or len(sha)!=64:
        raise RuntimeError("Verified private Node indexer not configured")
    builder=base64.b64decode(encoded,validate=True)
    if hashlib.sha256(builder).hexdigest()!=sha:
        raise RuntimeError("Private indexer SHA-256 mismatch")
    if b"pdfjs-dist/legacy/build/pdf.mjs" not in builder or b"sprDecodeRetainedIndex" not in builder:
        raise RuntimeError("Unrecognised private original-PDF indexer")
    # The injected private builder is SHA-verified BEFORE this narrow
    # compatibility adaptation. Its real-PDF AST and round-trip checks remain.
    # The retained cache version is owned by the active protected parser,
    # not a permanent number hard-coded into the 19 November builder.
    builder=builder.replace(
        br"source.match(/const SPR_RETAIN_VERSION=(\d+);/)",
        br"source.match(/(?:const|let|var)\s+SPR_RETAIN_VERSION\s*=\s*(\d+)\b/)")
    builder=builder.replace(b"cacheVersion!==4",
        b"(!Number.isInteger(cacheVersion)||cacheVersion<1||cacheVersion>32)")
    runtime_sha=hashlib.sha256(builder).hexdigest()
    script=home/"rc186-build-real-spr-index.mjs"
    if not script.is_file() or hashlib.sha256(script.read_bytes()).hexdigest()!=runtime_sha:
        tmp=home/(".indexer-"+str(os.getpid())+".tmp")
        tmp.write_bytes(builder)
        os.chmod(tmp,0o600)
        os.replace(tmp,script)
    if not (home/"package.json").exists():
        (home/"package.json").write_text('{"private":true,"type":"module"}\n')
    node=shutil.which("node")
    npm=shutil.which("npm")
    if node and npm:
        try:
            version=subprocess.run([node,"--version"],capture_output=True,text=True,timeout=8,check=True)
            major=int(version.stdout.strip().lstrip("v").split(".",1)[0])
            if major<22:node=None;npm=None
        except Exception:node=None;npm=None
    env=os.environ.copy()
    env["TMPDIR"]="/tmp"
    env["npm_config_cache"]="/tmp/spr-direct-indexer-npm-cache"
    nodebin=home/"node-v22.15.0-linux-x64"/"bin"
    if not node or not npm:
        if platform.machine() not in ("x86_64","amd64"):
            raise RuntimeError("Unsupported railway Node runtime architecture")
        nodebinary=nodebin/"node"
        npmbinary=nodebin/"npm"
        if not nodebinary.exists() or not npmbinary.exists():
            print("  [DIRECT INDEX RUNTIME] Preparing verified Node 22 LTS binary",flush=True)
            url="https://nodejs.org/dist/v22.15.0/"
            filename="node-v22.15.0-linux-x64.tar.xz"
            with urllib.request.urlopen(url+"SHASUMS256.txt",timeout=30) as r:
                checksums=r.read(40000).decode("ascii")
            matching=[line.split()[0] for line in checksums.splitlines()
                      if line.split()[-1]==filename and len(line.split())>=2]
            if len(matching)!=1:
                raise RuntimeError("Node.js LTS checksum unavailable")
            archive=home/filename
            try:
                with urllib.request.urlopen(url+filename,timeout=110) as r,archive.open("wb") as out:
                    total=0
                    while True:
                        chunk=r.read(1024*1024)
                        if not chunk:break
                        total+=len(chunk)
                        if total>45000000:raise RuntimeError("Node archive too large")
                        out.write(chunk)
                if hashlib.sha256(archive.read_bytes()).hexdigest()!=matching[0]:
                    raise RuntimeError("Verified Node.js archive digest mismatch")
                with tarfile.open(archive,"r:xz") as tar:
                    # Only expected relative entries from the checked archive.
                    for item in tar.getmembers():
                        p=pathlib.PurePosixPath(item.name)
                        root_name="node-v22.15.0-linux-x64"
                        if (p.is_absolute() or ".." in p.parts or
                            not (item.name==root_name or item.name.startswith(root_name+"/"))):
                            raise RuntimeError("Invalid Node.js archive entry")
                    tar.extractall(home,filter="data")
            finally:
                try:archive.unlink()
                except FileNotFoundError:pass
        node=str(nodebinary)
        npm=str(npmbinary)
        env["PATH"]=str(nodebin)+os.pathsep+env.get("PATH","")
    marker=home/".verified-dependencies"
    if not (marker.is_file() and marker.read_text().strip()=="pdfjs-dist@4.10.38+acorn@8"
            and (home/"node_modules"/"pdfjs-dist"/"package.json").is_file()
            and (home/"node_modules"/"acorn"/"package.json").is_file()):
        print("  [DIRECT INDEX RUNTIME] Installing pinned pdfjs/acorn locally",flush=True)
        install=subprocess.run([npm,"install","--no-save","--no-audit","--no-fund",
          "--ignore-scripts","pdfjs-dist@4.10.38","acorn@8"],
          cwd=home,env=env,capture_output=True,text=True,timeout=210)
        if install.returncode!=0:
            print("  [DIRECT INDEX NPM ERROR] code="+str(install.returncode)+
                  " stderr="+install.stderr[-650:].replace("\n"," ")+
                  " stdout="+install.stdout[-250:].replace("\n"," "),flush=True)
            raise RuntimeError("Pinned npm dependency installation failed")
        marker.write_text("pdfjs-dist@4.10.38+acorn@8\n")
    # Safely retire ONLY our previous, verified generated Node cache from the
    # small /data volume. Never traverse symlinks or remove user/roster data.
    legacy=pathlib.Path(DATA_ROOT)/"spr-direct-indexer"
    if legacy.is_dir() and not legacy.is_symlink():
        legacy_script=legacy/"rc186-build-real-spr-index.mjs"
        permitted={"rc186-build-real-spr-index.mjs","package.json",
                   "package-lock.json","node_modules",
                   "node-v22.15.0-linux-x64",".verified-dependencies"}
        try:
            names={p.name for p in legacy.iterdir()}
            if (legacy_script.is_file() and not legacy_script.is_symlink()
                and hashlib.sha256(legacy_script.read_bytes()).hexdigest()==sha
                and names.issubset(permitted)):
                shutil.rmtree(legacy)
                print("  [DIRECT INDEX STORAGE] Retired only verified obsolete generated Node cache",flush=True)
            else:
                print("  [DIRECT INDEX STORAGE] Previous cache not automatically removed; ownership check failed",flush=True)
        except Exception as exc:
            print("  [DIRECT INDEX STORAGE] Private-cache cleanup skipped: "+type(exc).__name__,flush=True)
    return node,script,home,env,sha

def _spr_direct_primary_sftp():
    import base64,io,os,paramiko
    host=os.environ.get("SFTP_HOST","").strip()
    username=os.environ.get("SFTP_USERNAME","").strip()
    b64=os.environ.get("SFTP_PRIVATE_KEY_B64","").strip()
    root=os.environ.get("SFTP_ROOT","").strip()
    if not all((host,username,b64,root)):
        raise RuntimeError("Existing Bodgybros SFTP connection unavailable")
    text=base64.b64decode(b64,validate=True).decode("utf-8")
    key=None
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=typ.from_private_key(io.StringIO(text));break
        except Exception:pass
    if key is None:raise RuntimeError("Bodgybros SFTP key cannot be opened")
    known=DATA_ROOT/"credentials"/"spr-sftp-known_hosts"
    if not known.is_file():raise RuntimeError("Bodgybros SFTP host verification missing")
    ssh=paramiko.SSHClient()
    ssh.load_host_keys(str(known))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=host,username=username,port=int(os.environ.get("SFTP_PORT") or 22),
                pkey=key,timeout=12,auth_timeout=12,banner_timeout=12,
                allow_agent=False,look_for_keys=False)
    sftp=ssh.open_sftp()
    sftp.get_channel().settimeout(50)
    return ssh,sftp,root

def _spr_direct_read(ftp,path,max_bytes=30_000_000):
    import hashlib
    if ftp.stat(path).st_size>max_bytes:raise RuntimeError("Remote PDF/parser size cap exceeded")
    chunks=[];total=0
    with ftp.open(path,"rb") as handle:
        # The cPanel SFTP server has substantial latency on sequential 32KiB
        # reads. Prefetch allows concurrent verified reads, avoiding minutes
        # of blocking on each future SPR PDF before Node can parse it.
        try:handle.prefetch(max_concurrent_requests=32)
        except Exception:pass
        while True:
            piece=handle.read(1024*1024)
            if not piece:break
            total+=len(piece)
            if total>max_bytes:raise RuntimeError("Remote source size limit exceeded")
            chunks.append(piece)
    return b"".join(chunks)

def _spr_direct_meta_good(meta_bytes,index_bytes,role,date,sha,engine_sha):
    import json
    try:
        m=json.loads(meta_bytes.decode("utf-8"))
        return (m.get("ok") is True and m.get("date")==date and m.get("role")==role
                and m.get("sourceSha")==sha and m.get("indexerEngineSha256")==engine_sha
                and m.get("parserBuild")==666 and m.get("pageLayoutBuild")==595
                and m.get("vectorDividerVersion")==1
                and m.get("compressedBytes")==len(index_bytes) and len(index_bytes)>100)
    except Exception:return False

def _spr_direct_verify_built(gz,meta,role,date,sha,engine_sha):
    import gzip,json
    raw=gz.read_bytes();info=json.loads(meta.read_text())
    decoded=json.loads(gzip.decompress(raw))
    pages=decoded.get("pages",[])
    records=decoded.get("records",[])
    shifts=decoded.get("shifts",[])
    invalid_divider_pages=[
        pg.get("pageNo",i+1) for i,pg in enumerate(pages)
        if not isinstance(pg.get("dividerXs"),list) or len(pg["dividerXs"])!=3
    ]
    checks={
        "meta_ok":info.get("ok") is True,
        "meta_date":info.get("date")==date,
        "meta_role":info.get("role")==role,
        "meta_sha":info.get("sourceSha")==sha,
        "meta_engine":info.get("indexerEngineSha256")==engine_sha,
        "meta_parser":info.get("parserBuild")==666,
        "meta_layout":info.get("pageLayoutBuild")==595,
        "meta_vector":info.get("vectorDividerVersion")==1,
        "meta_bytes":info.get("compressedBytes")==len(raw) and len(raw)>100,
        "pdf_sha":decoded.get("sourceSha")==sha,
        "date":decoded.get("date")==date,
        "role":decoded.get("role")==role,
        "parser":decoded.get("parserBuild")==666,
        "layout":decoded.get("pageLayoutBuild")==595,
        "vector":decoded.get("vectorDividerVersion")==1,
        "page_count":len(pages)>40,
        "dividers":not invalid_divider_pages,
        "record_count":len(records)>20,
        "shift_count":len(shifts)>10,
    }
    if not all(checks.values()):
        failed=",".join(key for key,ok in checks.items() if not ok)
        print("  [DIRECT INDEX REJECT PROOF] date="+date+" role="+role+
              " checks="+failed+" pages="+str(len(pages))+
              " records="+str(len(records))+" shifts="+str(len(shifts))+
              " divider_page_count="+str(len(invalid_divider_pages))+
              " divider_page_samples="+str(invalid_divider_pages[:8]),flush=True)
        raise RuntimeError("Original-PDF index failed exact source/date/parser checks")
    return raw,json.dumps(info,separators=(",",":")).encode("utf-8"),len(records),len(shifts)

def _spr_direct_primary_publish(ftp,folder,date,gz,meta):
    import hashlib,os
    parts=((date+".json.gz",gz),(date+".meta.json",meta))
    temporary=[]
    try:
        for name,payload in parts:
            target=folder+"/"+name
            tmp=target+".direct-"+str(os.getpid())+".tmp"
            temporary.append(tmp)
            with ftp.open(tmp,"wb") as writer:
                writer.write(payload)
            if ftp.stat(tmp).st_size!=len(payload) or hashlib.sha256(
                    _spr_direct_read(ftp,tmp,max_bytes=18_000_000)).digest()!=hashlib.sha256(payload).digest():
                raise RuntimeError("Staged Bodgybros index checksum mismatch")
            ftp.chmod(tmp,0o644)
        # Metadata last: readers never accept a partially written new index.
        for (name,_),tmp in zip(parts,temporary):
            ftp.posix_rename(tmp,folder+"/"+name)
    finally:
        for tmp in temporary:
            try:ftp.remove(tmp)
            except Exception:pass

def _spr_direct_index_one(job):
    import hashlib,json,os,pathlib,re,subprocess,tempfile
    date=str(job.get("date",""))
    role=str(job.get("role",""))
    sha=str(job.get("sha",""))
    if not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}",date) or role not in ("driver","guard") or not re.fullmatch(r"[a-f0-9]{64}",sha):
        raise RuntimeError("Untrusted queued SPR index parameters")
    from datetime import date as Date
    if Date.fromisoformat(date).isoformat()!=date:raise RuntimeError("Invalid date")
    folder="d" if role=="driver" else "g"
    label="Drivers" if role=="driver" else "Guards"
    filename="All "+label+" Combined "+date[8:10]+"_"+date[5:7]+"_"+date[:4]+".pdf"
    print("  [DIRECT INDEX JOB] "+date+" "+role+" checking published hashes",flush=True)
    ssh,ftp,root=_spr_direct_primary_sftp()
    print("  [DIRECT INDEX STAGE] "+date+" "+role+" primary_connected",flush=True)
    try:
        pdfdir=_spr_remote_subdir(root,"drivers" if role=="driver" else "guards")
        original_path=pdfdir+"/"+filename
        # Skip already verified dual-site indexes BEFORE downloading large PDFs.
        # Queued SHA comes from the original upload or remote source SHA check.
        # The live proprietary parser remains in its private account directory.
        private=os.environ["CPANEL_HOME"].rstrip("/")+"/sps-private-assets/rc230-proprietary-runtime.min.js"
        engine=_spr_direct_read(ftp,private,max_bytes=6_000_000)
        print("  [DIRECT INDEX STAGE] "+date+" "+role+" engine_read bytes="+str(len(engine)),flush=True)
        # The active engine is trusted from the primary private path, but
        # literal byte substring checks wrongly reject valid JS formatting.
        # Validate exact declared versions and every required vector parser
        # function; the Node builder also verifies AST and real-PDF output.
        parser_text=engine.decode("utf-8")
        mismatches=[]
        detected_retain=None
        for name,want in (("SPR_PARSER_BUILD",666),
                          ("SPR_PAGE_LAYOUT_BUILD",595),
                          ("SPR_RETAIN_VERSION",None)):
            found=re.search(r"\b(?:const|let|var)\s+"+re.escape(name)+
                            r"\s*=\s*(\d+)\b",parser_text)
            version=int(found.group(1)) if found else None
            if name=="SPR_RETAIN_VERSION":
                detected_retain=version
                if version is None or not (1<=version<=32):
                    mismatches.append(name+"="+str(version))
            elif version!=want:
                mismatches.append(name+"="+str(version))
        for name in ("rc242DrawnVerticalDividers",
                     "rc242DocumentDividerTemplate",
                     "rc242VerifiedPageDividers",
                     "reconstructSprLines","sprPagesMatchRole",
                     "interpretDocument","buildShiftSummaries",
                     "prepareShiftRuntimeIndexes",
                     "sprEncodeRetainedIndex","sprDecodeRetainedIndex",
                     "rc175OutgoingPlace"):
            if not re.search(r"\bfunction\s+"+re.escape(name)+r"\s*\(",parser_text):
                mismatches.append(name)
        if mismatches:
            raise RuntimeError("Active private SPR parser incompatible: "+
                               ",".join(mismatches[:8]))
        print("  [DIRECT INDEX PARSER VERIFIED] build=666 layout=595 retain="+
              str(detected_retain)+" vector_dividers=1",flush=True)
        engine_sha=hashlib.sha256(engine).hexdigest()
        remote_index=pdfdir.rsplit("/",1)[0]+"/i/"+folder
        # Ensure exact current indexes get skipped before expensive Node work.
        def primary_current():
            try:
                meta=_spr_direct_read(ftp,remote_index+"/"+date+".meta.json",max_bytes=100000)
                data=_spr_direct_read(ftp,remote_index+"/"+date+".json.gz",max_bytes=18_000_000)
                return _spr_direct_meta_good(meta,data,role,date,sha,engine_sha)
            except FileNotFoundError:return False
        primary=primary_current()
        print("  [DIRECT INDEX STAGE] "+date+" "+role+" primary_current="+str(primary),flush=True)
        secondary=False
        if _dual_enabled():
            print("  [DIRECT INDEX STAGE] "+date+" "+role+" kustom_connecting",flush=True)
            kssh,kftp=_dual_connection()
            print("  [DIRECT INDEX STAGE] "+date+" "+role+" kustom_connected",flush=True)
            kpdf=_dual_rel("spr/"+folder+"/"+filename)
            ksha=_dual_remote_sha(kssh,kftp,kpdf)
            print("  [DIRECT INDEX STAGE] "+date+" "+role+" kustom_source_hashed",flush=True)
            if ksha!=sha:
                raise RuntimeError("Kustom original PDF differs; refusing split sources")
            try:
                kmeta=_spr_direct_read(kftp,_dual_rel("spr/i/"+folder+"/"+date+".meta.json"),100000)
                kindex=_spr_direct_read(kftp,_dual_rel("spr/i/"+folder+"/"+date+".json.gz"),18_000_000)
                secondary=_spr_direct_meta_good(kmeta,kindex,role,date,sha,engine_sha)
            except FileNotFoundError:secondary=False
        print("  [DIRECT INDEX STAGE] "+date+" "+role+" secondary_current="+str(secondary),flush=True)
        if primary and (secondary or not _dual_enabled()):
            print("  [DIRECT INDEX CURRENT] "+date+" "+role+" both sites source verified",flush=True)
            return
        original=_spr_direct_read(ftp,original_path)
        if not original.startswith(b"%PDF") or hashlib.sha256(original).hexdigest()!=sha:
            raise RuntimeError("Original Bodgybros PDF has changed since upload")
        print("  [DIRECT INDEX BUILD] "+date+" "+role+" verified original source",flush=True)
        node,builder,home,env,indexer_sha=_spr_direct_index_runtime()
        with tempfile.TemporaryDirectory(prefix="spr-index-",dir=str(home)) as tmp:
            work=pathlib.Path(tmp)
            pdf=work/filename;pdf.write_bytes(original)
            parser=work/"active-parser.js";parser.write_bytes(engine)
            out=work/"output";out.mkdir()
            command=[node,"--max-old-space-size=4096",str(builder),str(parser),
                     str(pdf),date,role,str(out)]
            result=subprocess.run(command,cwd=home,env=env,text=True,
                         capture_output=True,timeout=360)
            if result.returncode:
                raise RuntimeError("Node PDF indexer failed "+str(result.returncode)+
                                   ": "+result.stderr[-320:].replace("\n"," "))
            gz=out/(date+".json.gz")
            meta=out/(date+".meta.json")
            if not gz.is_file() or not meta.is_file():
                raise RuntimeError("Exact Node index outputs missing")
            info=json.loads(meta.read_text())
            info["indexerEngineSha256"]=engine_sha
            meta.write_text(json.dumps(info,separators=(",",":")))
            compressed,sidecar,records,shifts=_spr_direct_verify_built(
                gz,meta,role,date,sha,engine_sha)
            if not primary:_spr_direct_primary_publish(ftp,remote_index,date,compressed,sidecar)
            if _dual_enabled() and not secondary:
                _dual_store("spr/i/"+folder+"/"+date+".json.gz",compressed)
                _dual_store("spr/i/"+folder+"/"+date+".meta.json",sidecar)
            print("  [DIRECT INDEX VERIFIED] "+date+" "+role+
                  " records="+str(records)+" shifts="+str(shifts)+
                  " primary="+str(not primary)+" mirror="+str(_dual_enabled() and not secondary),
                  flush=True)
    finally:
        try:ftp.close()
        except Exception:pass
        ssh.close()

def _spr_index_background(jobs):
    # REPLACES the old Playwright wait_for_function(__SPR_INDEXER_API.build)
    # background path. Uploads have already succeeded before reaching here.
    if not _SPR_INDEX_RUNNING.acquire(blocking=False):
        print("  [DIRECT INDEX DEFERRED] Worker already active; next upload can retry",flush=True)
        return
    try:
        seen=set()
        for job in jobs:
            key=(job.get("date"),job.get("role"))
            if key in seen:continue
            seen.add(key)
            try:_spr_direct_index_one(job)
            except Exception as exc:
                print("  [DIRECT INDEX FAILED] "+str(key[0])+" "+str(key[1])+
                      " "+type(exc).__name__+": "+str(exc)[:240],flush=True)
    finally:
        try:_dual_release_connection()
        except Exception:pass
        _SPR_INDEX_RUNNING.release()

def _spr_direct_startup_catchup():
    print("  [DIRECT INDEX CATCHUP START] scanning original uploads after 20s",flush=True)
    # One bounded recovery scan after startup so already published future PDFs
    # are not missed if the previous browser indexer timed out during upload.
    import datetime,hashlib,os,re,time
    from zoneinfo import ZoneInfo
    time.sleep(20)
    if not _SPR_INDEX_RUNNING.acquire(blocking=False):
        print("  [DIRECT INDEX CATCHUP] Upload indexer active; skipping duplicate",flush=True)
        return
    # Release before handing date/role jobs to the normal locked worker.
    _SPR_INDEX_RUNNING.release()
    try:
        print("  [DIRECT INDEX CATCHUP CONNECT] Opening trusted primary SFTP",flush=True)
        ssh,ftp,root=_spr_direct_primary_sftp()
        print("  [DIRECT INDEX CATCHUP CONNECTED] Primary SFTP ready",flush=True)
        jobs=[]
        try:
            today=datetime.datetime.now(ZoneInfo("Australia/Sydney")).date()
            import shlex
            # Never list the whole years-long SPR directory. Test only the
            # bounded recent/future filenames, then SHA the existing sources.
            for role,label in (("driver","Drivers"),("guard","Guards")):
                source=_spr_remote_subdir(root,label.lower())
                print("  [DIRECT INDEX CATCHUP SCAN] role="+role+" dates=34",flush=True)
                found=0
                for offset in range(-3,31):
                    day=today+datetime.timedelta(days=offset)
                    filename="All "+label+" Combined "+day.strftime("%d_%m_%Y")+".pdf"
                    source_file=source+"/"+filename
                    try:
                        stat=ftp.stat(source_file)
                    except FileNotFoundError:
                        continue
                    if stat.st_size<1000 or stat.st_size>30000000:continue
                    digest=None
                    try:
                        cmd="sha256sum -- "+shlex.quote(source_file)
                        stdin,stdout,stderr=ssh.exec_command(cmd,timeout=12)
                        stdout.channel.settimeout(22)
                        line=stdout.read(240).decode("ascii","replace")
                        rc=stdout.channel.recv_exit_status()
                        stdin.close();stdout.close();stderr.close()
                        if rc==0 and re.match(r"^[0-9a-f]{64}  ",line):
                            digest=line[:64]
                    except Exception:pass
                    if digest is None:
                        data=_spr_direct_read(ftp,source_file)
                        if not data.startswith(b"%PDF"):continue
                        digest=hashlib.sha256(data).hexdigest()
                    jobs.append({"date":day.isoformat(),"role":role,
                                 "sha":digest,
                                 "site":"https://www.bodgybros.com/sps"})
                    found+=1
                    print("  [DIRECT INDEX CATCHUP SOURCE] role="+role+
                          " date="+day.isoformat()+" verified=yes",flush=True)
                print("  [DIRECT INDEX CATCHUP SCAN COMPLETE] role="+role+
                      " available="+str(found),flush=True)
        finally:
            ftp.close();ssh.close()
        if jobs:
            # Index future releases first so Friday/Saturday or Sunday/Monday
            # crew data is ready before its service date, then today, then past.
            jobs.sort(key=lambda j:(0 if j["date"]>today.isoformat()
                                    else 1 if j["date"]==today.isoformat()
                                    else 2,j["date"],j["role"]))
            print("  [DIRECT INDEX CATCHUP] Original-SHA verified candidates="+str(len(jobs)),flush=True)
            _spr_index_background(jobs)
    except Exception as exc:
        print("  [DIRECT INDEX CATCHUP FAILED] "+type(exc).__name__+
              ": "+str(exc)[:200],flush=True)

def _spr_secondary_catchup():
    # The prior version also used the removed browser-indexer API.
    # The bounded new startup scanner handles both current and future dates.
    return None

print("  [DIRECT INDEX RUNTIME] enabled="+str(os.environ.get("SPR_DIRECT_INDEXER_ENABLED","1").strip()=="1"),flush=True)
if os.environ.get("SPR_DIRECT_INDEXER_ENABLED","1").strip()=="1":
    threading.Thread(target=_spr_direct_startup_catchup,
                     name="spr-direct-index-catchup",daemon=True).start()
'''
def apply(path: Path):
    source=path.read_text(encoding="utf-8")
    if MARKER in source:
        print("[DIRECT INDEX] Already installed",flush=True)
        return
    tree=ast.parse(source)
    functions={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
    required={"upload_pdf","run_update","_spr_index_background",
              "_spr_remote_subdir","_dual_store",
              "_dual_connection","_dual_enabled","_dual_release_connection"}
    missing=required-functions
    if missing:
        raise RuntimeError("Expected upload/index/SFTP functions missing: "+str(sorted(missing)))
    if "_SPR_INDEX_RUNNING" not in source:
        raise RuntimeError("Existing index lock missing")
    main=[n for n in tree.body if isinstance(n,ast.If) and
          "__name__" in (ast.get_source_segment(source,n.test) or "")]
    if not main:
        raise RuntimeError("Updater entrypoint missing")
    lines=source.splitlines(keepends=True)
    at=main[-1].lineno-1
    updated="".join(lines[:at])+EXTENSION+"\n"+"".join(lines[at:])
    compile(updated,str(path),"exec")
    temp=path.with_suffix(".direct-index-staged")
    temp.write_text(updated,encoding="utf-8")
    temp.replace(path)
    print("[DIRECT INDEX READY] Verified original PDF Node worker replaces browser API; dual-site upload/rosters unchanged",flush=True)

if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("Usage: patch.py path/to/spr_online_updater.py")
    apply(Path(sys.argv[1]))
