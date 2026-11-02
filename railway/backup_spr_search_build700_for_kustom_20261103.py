#!/usr/bin/env python3
"""Private application-only recovery archive for moving SPR Search Build 700.

Copies the CURRENT live Bodgybros /sps application files from authenticated
SFTP into /data/backups on the owner's private Railway volume.
- No public links, no GitHub uploads, no writes to either website.
- Skips bulk SPR and roster PDFs: these will be transferred directly once
  the separate Kustom hosting account authorizes SFTP access.
- Preserves .htaccess/PHP/JS/CSS/assets and all versioned JS fixes.
"""
import os,io,base64,hashlib,posixpath,stat,zipfile,json,tempfile,datetime
from pathlib import Path
import paramiko

DEST=Path("/data/backups/spr-kustom-migration")
ZIP_NAME="SPR-Search-Build700-Kustom-App-20261103.zip"
SKIP_DIRS={"spr","rosters","roster","backups","backup","tmp","temp","logs",".git","node_modules"}
SKIP_ENDS=(".zip",".tar",".tar.gz",".7z",".pdf",".bak",".old",".log")
MAX_FILES=1500
MAX_BYTES=380*1024*1024
MAX_PER_FILE=60*1024*1024

def digest_file(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for buf in iter(lambda:f.read(1024*1024),b""):
            h.update(buf)
    return h.hexdigest()

def parse_sftp_key():
    raw=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode("utf-8")
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:return cls.from_private_key(io.StringIO(raw))
        except Exception:pass
    raise RuntimeError("Existing site SSH key unusable")

def normalize_root():
    root=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
    if root.endswith("/sps/spr"):root=root[:-4]
    elif root.endswith("/public_html"):root+="/sps"
    if not root.endswith("/sps"):raise RuntimeError("Expected authenticated /sps source root")
    return root

def main():
    if not os.path.isdir("/data"):
        raise RuntimeError("Persistent Railway /data volume unavailable")
    DEST.mkdir(parents=True,exist_ok=True)
    os.chmod(DEST,0o700)
    final=DEST/ZIP_NAME
    if final.exists():
        print("[KUSTOM BACKUP] Already exists, bytes:",final.stat().st_size,"SHA256:",digest_file(final)[:18],flush=True)
        return
    ssh=paramiko.SSHClient()
    ssh.load_host_keys("/data/credentials/spr-sftp-known_hosts")
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ["SFTP_HOST"],username=os.environ["SFTP_USERNAME"],
                port=int(os.environ.get("SFTP_PORT") or 22),
                pkey=parse_sftp_key(),timeout=12,auth_timeout=12,banner_timeout=12,
                allow_agent=False,look_for_keys=False)
    root=normalize_root()
    manifest={"source":"SPR Search current working Build 700 at /sps",
              "intended_destination":"kustomvinyls.com/sps",
              "snapshot_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "scope":"Application and static assets only; SPR and roster PDF stores transfer separately",
              "files":[]}
    staged=None
    try:
        with ssh.open_sftp() as ftp:
            stack=[("",root)]
            staged_fd,staged=tempfile.mkstemp(prefix=".spr-kustom-",suffix=".zip",dir=DEST)
            os.close(staged_fd)
            total=0; count=0; saw_js=False; saw_index=False
            with zipfile.ZipFile(staged,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=5,allowZip64=True) as archive:
                while stack:
                    relative,remote=stack.pop()
                    for entry in ftp.listdir_attr(remote):
                        name=entry.filename
                        if name in (".",".."):continue
                        full=posixpath.join(remote,name)
                        rel=posixpath.join(relative,name)
                        if rel.startswith("/") or ".." in rel.split("/"):
                            raise RuntimeError("Unsafe remote path")
                        if stat.S_ISLNK(entry.st_mode):continue
                        if stat.S_ISDIR(entry.st_mode):
                            if name.lower() in SKIP_DIRS:continue
                            stack.append((rel,full))
                            continue
                        if not stat.S_ISREG(entry.st_mode):continue
                        if name.lower().endswith(SKIP_ENDS):continue
                        if entry.st_size>MAX_PER_FILE:
                            raise RuntimeError("Application file unexpectedly large; abort whole backup")
                        total+=entry.st_size
                        count+=1
                        if total>MAX_BYTES or count>MAX_FILES:
                            raise RuntimeError("App backup exceeded safe cap, incomplete file refused")
                        digest=hashlib.sha256()
                        with ftp.open(full,"rb") as src,archive.open(rel,"w") as out:
                            while True:
                                chunk=src.read(1024*1024)
                                if not chunk:break
                                out.write(chunk);digest.update(chunk)
                        manifest["files"].append({"name":rel,"bytes":entry.st_size,"sha256":digest.hexdigest()})
                        if rel=="index.php":saw_index=True
                        if rel=="script-700-fromto-locations-v1.js":saw_js=True
                if not saw_index or not saw_js:
                    raise RuntimeError("Current Build700 index.php or latest versioned script missing: refuse snapshot")
                archive.writestr("KUSTOM-MIGRATION-MANIFEST.json",json.dumps(manifest,indent=2))
                archive.writestr("KUSTOM-MIGRATION-INSTRUCTIONS.txt",
                     "PRIVATE BUILD700 APPLICATION RECOVERY SNAPSHOT\n"
                     "Do not upload to public GitHub. Contains application PHP and configuration.\n"
                     "Transfer original SPR PDFs and roster PDF/cache data separately.\n"
                     "Review absolute Bodgybros URLs and Kustom hosting database/auth settings before cutover.\n"
                     "Keep the original Bodgybros installation untouched.\n")
            with zipfile.ZipFile(staged) as check:
                if check.testzip() is not None:
                    raise RuntimeError("Application backup CRC validation failed")
            os.chmod(staged,0o600)
            os.replace(staged,final);staged=None
            print("[KUSTOM BACKUP] PRIVATE archive created on Railway volume",flush=True)
            print("[KUSTOM BACKUP] app files:",count,"uncompressed bytes:",total,
                  "archive bytes:",final.stat().st_size,flush=True)
            print("[KUSTOM BACKUP] SHA256:",digest_file(final)[:28],flush=True)
            print("[KUSTOM BACKUP] stored privately:",str(final),flush=True)
            print("[KUSTOM BACKUP] all SPR and roster PDFs remain in source SFTP; no website was modified",flush=True)
    finally:
        ssh.close()
        if staged and os.path.exists(staged):
            os.unlink(staged)
if __name__=="__main__":
    main()
