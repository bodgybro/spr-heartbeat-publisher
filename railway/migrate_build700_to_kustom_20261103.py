#!/usr/bin/env python3
"""Safely prepare and publish independent SPR Search Build 700 on Kustom Vinyls.

- Input: SHA-checked private Railway app backup of live Build700.
- Destination: separate authenticated cPanel Kustom hosting account, with
  user-authorized migration SSH key and previously checked SSH host key.
- Never touches source files. Does not use missing Bodgybros public DNS.
- New site is assembled outside webroot and then atomically renamed to /sps.
- All files are uploaded through encrypted SFTP, hashed and checked.
- Includes roster files/cache plus available current SPR Drivers/Guards PDFs.
- Older historical SPR PDFs are intentionally not transferred in the first
  release to fit shared hosting disk space; manifest reports selection.
- Does NOT alter ongoing Bodgybros Railway update targets or schedule.
"""
import os,io,base64,hashlib,json,posixpath,re,stat,datetime,zipfile,time
from pathlib import Path
import paramiko

ARCHIVE=Path("/data/backups/spr-kustom-migration/SPR-Search-Build700-Kustom-App-20261103.zip")
DEST_PARENT="/home10/kustomvi/public_html"
DEST_ROOT=DEST_PARENT+"/sps"
DEST_STAGE="/home10/kustomvi/.spr-kustom-build700-staging-20261103"
SRC_HOST=os.environ["SFTP_HOST"]
SRC_USER=os.environ["SFTP_USERNAME"]
DEST_HOST="cp-wc18.per01.ds.network"
DEST_USER="kustomvi"
DEST_KEY="/data/credentials/kustom-transfer/id_ed25519"
MIN_DATE=datetime.date(2026,10,29)
MAX_TOTAL_BYTES=800*1024*1024
MIN_SPARE_BYTES=45*1024*1024
SOURCE_ROOT=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
if SOURCE_ROOT.endswith("/sps/spr"):SOURCE_ROOT=SOURCE_ROOT[:-4]
elif SOURCE_ROOT.endswith("/public_html"):SOURCE_ROOT+="/sps"
if not SOURCE_ROOT.endswith("/sps"):raise RuntimeError("Unexpected source SFTP root")
STATIC_REGEX=re.compile(r"^All (Drivers|Guards) Combined (\d\d)_(\d\d)_(20\d\d\d\d)\.pdf$",re.I)
TEXT_SUFFIXES={".js",".php",".html",".css",".json",".txt",".htaccess",".svg",".webmanifest"}
state={"files":0,"bytes":0,"pdfs":0,"rosters":0,"existing":0,"errors":0}
start=time.monotonic()

def log(*items):print("[KUSTOM BUILD700 TRANSFER]",*items,flush=True)
def digest(b):return hashlib.sha256(b).hexdigest()
def key_from_source():
    raw=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode("utf-8")
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:return cls.from_private_key(io.StringIO(raw))
        except Exception:pass
    raise RuntimeError("Existing Bodgybros SFTP key unavailable")
def connect(host,user,key,known,port):
    cli=paramiko.SSHClient()
    cli.load_host_keys(known)
    cli.set_missing_host_key_policy(paramiko.RejectPolicy())
    cli.connect(hostname=host,username=user,pkey=key,port=port,
      timeout=15,auth_timeout=15,banner_timeout=15,look_for_keys=False,allow_agent=False)
    return cli

def mkdir_all(sftp,path):
    pieces=path.split("/")
    cur=""
    for piece in pieces:
        if not piece:continue
        cur+="/"+piece
        try:attr=sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur,0o755)
        else:
            if not stat.S_ISDIR(attr.st_mode):raise RuntimeError("Cannot make folder; file exists")
def remote_digest(sftp,path):
    h=hashlib.sha256()
    with sftp.open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1048576),b""):
            h.update(chunk)
    return h.hexdigest()
def copy_bytes(dest,rel,data,mode=0o644):
    if len(data)+state["bytes"]>MAX_TOTAL_BYTES:raise RuntimeError("Transfer byte cap reached")
    target=posixpath.join(DEST_STAGE,rel)
    mkdir_all(dest,posixpath.dirname(target))
    newdigest=digest(data)
    try:
        st=dest.stat(target)
        if st.st_size==len(data) and remote_digest(dest,target)==newdigest:
            state["existing"]+=1
            return
    except FileNotFoundError:pass
    tmp=target+".transfer-"+str(os.getpid())
    try:
        with dest.open(tmp,"wb") as f:f.write(data)
        if remote_digest(dest,tmp)!=newdigest:raise RuntimeError("Uploaded SHA mismatch "+rel)
        dest.chmod(tmp,mode)
        dest.posix_rename(tmp,target)
        if remote_digest(dest,target)!=newdigest:raise RuntimeError("Published staged SHA mismatch "+rel)
    finally:
        try:dest.remove(tmp)
        except OSError:pass
    state["files"]+=1
    state["bytes"]+=len(data)
    if state["files"]%12==0:log("copied",state["files"],"files",state["bytes"],"bytes",flush=True)
def copy_stream(src,dest,rel,size):
    if size+state["bytes"]>MAX_TOTAL_BYTES:
        raise RuntimeError("Transfer byte cap reached during "+rel)
    origin=posixpath.join(SOURCE_ROOT,rel)
    target=posixpath.join(DEST_STAGE,rel)
    mkdir_all(dest,posixpath.dirname(target))
    try:
        st=dest.stat(target)
        if st.st_size==size:
            # For resumed copies verify against source rather than trusting size.
            h=hashlib.sha256()
            with src.open(origin,"rb") as f:
                for chunk in iter(lambda:f.read(1048576),b""):h.update(chunk)
            if remote_digest(dest,target)==h.hexdigest():
                state["existing"]+=1
                return
    except FileNotFoundError:pass
    tmp=target+".transfer-"+str(os.getpid())
    expected=hashlib.sha256()
    try:
        with src.open(origin,"rb") as fin,dest.open(tmp,"wb") as fout:
            while True:
                chunk=fin.read(1048576)
                if not chunk:break
                fout.write(chunk);expected.update(chunk)
            fout.flush()
        st=dest.stat(tmp)
        if st.st_size!=size:raise RuntimeError("Uploaded size mismatch "+rel)
        if remote_digest(dest,tmp)!=expected.hexdigest():raise RuntimeError("Uploaded SHA mismatch "+rel)
        dest.chmod(tmp,0o644)
        dest.posix_rename(tmp,target)
    finally:
        try:dest.remove(tmp)
        except OSError:pass
    state["files"]+=1;state["bytes"]+=size
    if rel.lower().endswith(".pdf"):state["pdfs"]+=1
    if rel.startswith("rosters/"):state["rosters"]+=1
    log("COPY OK",rel,"bytes",size)

def selected_roster_source(src):
    """Return all current stored roster/cache files, not obsolete releases."""
    dirs=(".roster-cache",".roster-relay",".spr-updater","rosters")
    selected=[]
    for folder in dirs:
        queue=[folder]
        while queue:
            rel=queue.pop()
            try:entries=src.listdir_attr(posixpath.join(SOURCE_ROOT,rel))
            except FileNotFoundError:continue
            for item in entries:
                n=item.filename
                if n in (".","..") or n.endswith(".tmp") or n.endswith(".part"):continue
                child=posixpath.join(rel,n)
                if stat.S_ISLNK(item.st_mode):continue
                if stat.S_ISDIR(item.st_mode):
                    queue.append(child)
                elif stat.S_ISREG(item.st_mode):
                    selected.append((child,item.st_size))
    return sorted(selected)

def selected_spr_source(src):
    """Most recent 29 Oct-03 Nov PDFs plus associated small index files."""
    out=[]
    byrole={"d":0,"g":0}
    for role in ("d","g"):
        relfolder="spr/"+role
        try:items=src.listdir_attr(posixpath.join(SOURCE_ROOT,relfolder))
        except FileNotFoundError:continue
        for item in items:
            if not stat.S_ISREG(item.st_mode):continue
            name=item.filename
            rel=posixpath.join(relfolder,name)
            m=STATIC_REGEX.fullmatch(name)
            if m:
                file_role="d" if m.group(1).lower()=="drivers" else "g"
                if file_role!=role:continue
                day=datetime.date(int(m.group(4)),int(m.group(3)),int(m.group(2)))
                if day<MIN_DATE:continue
                out.append((rel,item.st_size))
                byrole[role]+=1
            elif (not name.lower().endswith(".pdf")) and item.st_size<=3000000:
                out.append((rel,item.st_size))
    log("Selected up-to-date source SPR PDFs",byrole)
    if min(byrole.values())<1:
        raise RuntimeError("Missing available recent SPR PDF for either Drivers or Guards: "+str(byrole))
    return sorted(out)
def transform(relative,raw):
    """Rewrite references to origin site, leaving the executable semantics intact."""
    ext=posixpath.splitext(relative)[1].lower()
    if posixpath.basename(relative)==".htaccess":ext=".htaccess"
    if ext not in TEXT_SUFFIXES or len(raw)>7000000:return raw
    replacements=(
        (b"https://www.bodgybros.com/sps",b"https://www.kustomvinyls.com/sps"),
        (b"https://bodgybros.com/sps",b"https://www.kustomvinyls.com/sps"),
        (b"//www.bodgybros.com/sps",b"//www.kustomvinyls.com/sps"),
        (b"//bodgybros.com/sps",b"//www.kustomvinyls.com/sps"),
    )
    out=raw
    for original,replacement in replacements:out=out.replace(original,replacement)
    return out

def main():
    if not ARCHIVE.is_file():raise RuntimeError("Private Build700 app archive unavailable")
    source=connect(SRC_HOST,SRC_USER,key_from_source(),
                  "/data/credentials/spr-sftp-known_hosts",int(os.environ.get("SFTP_PORT") or 22))
    target=connect(DEST_HOST,DEST_USER,paramiko.Ed25519Key.from_private_key_file(DEST_KEY),
                  "/data/credentials/kustom-transfer/known_hosts",22)
    try:
        with source.open_sftp() as src,target.open_sftp() as dest,zipfile.ZipFile(ARCHIVE) as app:
            if app.testzip() is not None:raise RuntimeError("Private backup CRC failed")
            entries=[i for i in app.infolist() if not i.is_dir() and not i.filename.startswith("KUSTOM-MIGRATION-")]
            if not any(x.filename=="script-700-fromto-locations-v1.js" for x in entries):
                raise RuntimeError("Backup doesn't contain current known-good JS")
            if not any(x.filename=="index.php" for x in entries):
                raise RuntimeError("Backup missing index.php")
            # Never overwrite any existing production /sps directory.
            try:dest.stat(DEST_ROOT)
            except FileNotFoundError:pass
            else:
                log("Production /sps already exists. Refusing to overwrite.")
                return
            mkdir_all(dest,DEST_STAGE)
            try:
                v=dest.statvfs(DEST_PARENT)
                free=v.f_bavail*v.f_frsize
                log("Destination free bytes",free)
                if free<MIN_SPARE_BYTES+80*1024*1024:
                    raise RuntimeError("Not enough free hosting space")
            except OSError as exc:
                log("Hosting quota query unavailable",type(exc).__name__)
            # Metadata planning first: do not transfer until required files present.
            rosters=selected_roster_source(src)
            spr_files=selected_spr_source(src)
            estimated=sum(x.file_size for x in entries)+sum(sz for _,sz in rosters)+sum(sz for _,sz in spr_files)
            log("PLAN app_files",len(entries),"roster_files",len(rosters),"spr_files",len(spr_files),"planned_bytes",estimated)
            if estimated>MAX_TOTAL_BYTES:
                raise RuntimeError("Copy plan exceeds first-phase shared-hosting cap")
            try:
                v=dest.statvfs(DEST_PARENT)
                available=v.f_bavail*v.f_frsize
                if available<estimated+MIN_SPARE_BYTES:raise RuntimeError("Hosting storage insufficient for current PDFs and roster copy")
            except OSError as exc:
                log("Storage verification unavailable",type(exc).__name__)
            # Write working application before large PDFs, everything outside webroot.
            for info in entries:
                rel=info.filename
                if rel.startswith("/") or ".." in rel.split("/"):
                    raise RuntimeError("Backup has unsafe member path")
                data=transform(rel,app.read(info))
                copy_bytes(dest,rel,data)
            log("Working Build700 app files copied",len(entries))
            for rel,size in rosters:
                copy_stream(src,dest,rel,size)
            log("Roster cache and PDFs copied",len(rosters))
            for rel,size in spr_files:
                copy_stream(src,dest,rel,size)
            log("Current SPR PDF files copied",len(spr_files))
            for needed in ("index.php","index.html","script.js","script-700-fromto-locations-v1.js",
                           "roster-cache-api.php","roster-relay-api.php","spr-index-api.php"):
                dest.stat(posixpath.join(DEST_STAGE,needed))
            # Stage ready: make a private record that is NOT served by website.
            details={"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "copied_files":state["files"],"copied_bytes":state["bytes"],
                    "recent_spr_files":[name for name,_ in spr_files],
                    "roster_files":len(rosters),"latest_js":"script-700-fromto-locations-v1.js",
                    "note":"Earlier historical SPR PDFs not yet migrated; Bodgybros original and Railway updater unchanged"}
            private_file="/data/backups/spr-kustom-migration/kustom-20261103-first-copy.json"
            with open(private_file,"w") as f:json.dump(details,f,indent=2)
            # Only now make new site available. No preexisting target was replaced.
            dest.rename(DEST_STAGE,DEST_ROOT)
            log("PUBLISHED",DEST_ROOT)
            log("FINISHED copied_files",state["files"],"copied_bytes",state["bytes"],
                "pdfs_copied",state["pdfs"],"roster_files",state["rosters"],
                "existing_verified",state["existing"],"elapsed_seconds",round(time.monotonic()-start,1))
    finally:
        source.close();target.close()

if __name__=="__main__":
    try:main()
    except Exception as exc:
        log("NOT PUBLISHED / FAILED",type(exc).__name__,str(exc)[:250])
        raise
