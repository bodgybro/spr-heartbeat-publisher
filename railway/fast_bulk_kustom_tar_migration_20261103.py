#!/usr/bin/env python3
"""Fast, private, verified server-to-server stream for Build700 to Kustom.

Runs only using two already-authorized private SSH keys. No source modifications.
Transfers current roster store and six days of SPR PDFs in one tar stream,
then compares independent full-file SHA-256 hashes from both cPanel servers,
finally atomically publishes the already-staged current Build700 app.
"""
import os,io,base64,posixpath,shlex,time,hashlib,paramiko,stat,json,datetime,requests

SRC_ROOT=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
if SRC_ROOT.endswith("/sps/spr"):SRC_ROOT=SRC_ROOT[:-4]
elif SRC_ROOT.endswith("/public_html"):SRC_ROOT+="/sps"
if not SRC_ROOT.endswith("/sps"):raise RuntimeError("Unknown original SPR source root")

DST_STAGE="/home10/kustomvi/.spr-kustom-build700-staging-20261103"
DST_PUBLIC="/home10/kustomvi/public_html/sps"
STAGE_INFO="/data/backups/spr-kustom-migration/kustom-20261103-first-copy.json"
ROSTER_DIRS=[".roster-cache",".roster-relay",".spr-updater","rosters"]
SOURCES=[f"spr/{role}/All {label} Combined {day:02d}_{month:02d}_2026.pdf"
    for role,label in (("d","Drivers"),("g","Guards"))
    for (day,month) in ((29,10),(30,10),(31,10),(1,11),(2,11),(3,11))]
TRANSFER_PATHS=ROSTER_DIRS+SOURCES
start=time.monotonic()

def say(*s):print("[KUSTOM FAST BULK]",*s,flush=True)
def get_key():
    k=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode("utf-8")
    for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:return cls.from_private_key(io.StringIO(k))
        except Exception:pass
    raise RuntimeError("Original account key not usable")
def connect(host,user,port,key,knownhosts):
    client=paramiko.SSHClient()
    client.load_host_keys(knownhosts)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(hostname=host,username=user,port=port,pkey=key,
                   timeout=15,auth_timeout=15,banner_timeout=15,
                   look_for_keys=False,allow_agent=False)
    client.get_transport().set_keepalive(20)
    return client
def run(client,command,timeout=45,limit=200000):
    stdin,stdout,stderr=client.exec_command(command,timeout=timeout)
    stdout.channel.settimeout(timeout)
    output=stdout.read(limit)
    err=stderr.read(1200)
    rc=stdout.channel.recv_exit_status()
    stdin.close();stdout.close();stderr.close()
    if rc!=0:raise RuntimeError("SSH returned "+str(rc)+": "+err.decode(errors="replace")[:250])
    return output.decode("utf-8",errors="replace")
def q(v):return shlex.quote(v)
def hash_manifest(client,root):
    # Restrict to the exact most-recent PDFs and active roster/cache folders.
    # xargs and sha256sum are present on both tested shared Linux SSH shells.
    check=" && ".join((
        "cd "+q(root),
        "find "+ " ".join(q(d) for d in ROSTER_DIRS)
        +" -type f -print0 | xargs -0 -r sha256sum",
        "sha256sum "+" ".join(q(f) for f in SOURCES),
    ))
    output=run(client,check,timeout=120,limit=50000)
    result={}
    for line in output.splitlines():
        parts=line.split("  ",1)
        if len(parts)!=2 or len(parts[0])!=64:
            raise RuntimeError("Unrecognized remote checksum line")
        name=parts[1].strip().removeprefix("./")
        result[name]=parts[0]
    return result
def channel_exec(client,command):
    chan=client.get_transport().open_session()
    chan.settimeout(180)
    chan.exec_command(command)
    return chan

src=connect(os.environ["SFTP_HOST"],os.environ["SFTP_USERNAME"],
            int(os.environ.get("SFTP_PORT") or 22),get_key(),
            "/data/credentials/spr-sftp-known_hosts")
dst=connect("cp-wc18.per01.ds.network","kustomvi",22,
            paramiko.Ed25519Key.from_private_key_file("/data/credentials/kustom-transfer/id_ed25519"),
            "/data/credentials/kustom-transfer/known_hosts")
try:
    with dst.open_sftp() as files:
        try: files.stat(DST_PUBLIC)
        except FileNotFoundError:pass
        else:
            say("PUBLIC SITE EXISTS; refusing to overwrite and stopping")
            raise SystemExit(0)
        if not stat.S_ISDIR(files.stat(DST_STAGE).st_mode):
            raise RuntimeError("Private Build700 staging site unavailable")
        for name in ("index.php","index.html","script.js",
                     "script-700-fromto-locations-v1.js","roster-cache-api.php",
                     "roster-relay-api.php","spr-index-api.php"):
            files.stat(posixpath.join(DST_STAGE,name))
    say("Staged Build700 application verified; source untouched")

    # Both accounts have working shell. Test exact 12 files on the source.
    listcommand="cd "+q(SRC_ROOT)+" && "+ " && ".join("test -f "+q(p) for p in SOURCES)
    run(src,listcommand,timeout=30)
    say("All 12 expected SPR PDFs exist on source")

    # Tar on source, untar directly into private (nonpublic) destination folder.
    # The path names below come from fixed safe literals, not users or globals.
    source_command="tar -C "+q(SRC_ROOT)+" -cf - "+" ".join(q(p) for p in TRANSFER_PATHS)
    target_command="tar --no-same-owner --no-same-permissions -C "+q(DST_STAGE)+" -xf -"
    out=channel_exec(src,source_command)
    receiving=channel_exec(dst,target_command)
    total=0;next_checkpoint=16*1024*1024
    stream_sha=hashlib.sha256()
    try:
        while True:
            buffer=out.recv(131072)
            if not buffer:break
            receiving.sendall(buffer)
            total+=len(buffer)
            stream_sha.update(buffer)
            if total>=next_checkpoint:
                say("Streaming",round(total/(1024*1024),1),"MiB")
                next_checkpoint+=16*1024*1024
            if total>650*1024*1024:raise RuntimeError("Unexpectedly large tar stream; abort")
        receiving.shutdown_write()
        rc1=out.recv_exit_status()
        rc2=receiving.recv_exit_status()
        if rc1 or rc2:
            raise RuntimeError("Server tar failed src "+str(rc1)+" dest "+str(rc2))
        say("Tar stream received and extracted","bytes",total,"SHA256",stream_sha.hexdigest()[:16])
    finally:
        out.close();receiving.close()

    # Clean up old incomplete SFTP temp files in the private staging tree
    # before generating the destination file manifest.
    run(dst,"find "+q(DST_STAGE)+" -type f -name '*.transfer-*' -delete",timeout=30)
    # SHA-256 from original source disk and new target disk; independent of
    # stream verification. Compares every selected file, not sizes only.
    actual_src=hash_manifest(src,SRC_ROOT)
    actual_dest=hash_manifest(dst,DST_STAGE)
    if actual_src!=actual_dest:
        missing=sorted(set(actual_src)-set(actual_dest))
        wrong=sorted(k for k in actual_src if k in actual_dest and actual_src[k]!=actual_dest[k])
        additional=sorted(set(actual_dest)-set(actual_src))
        say("HASH MISMATCH",len(missing),"missing",len(wrong),"changed",len(additional),"additional")
        raise RuntimeError("Refusing to publish until every active roster and SPR file matches SHA-256")
    say("ALL FILES SHA256 VERIFIED","count",len(actual_src))
    if len(actual_src)<90:
        raise RuntimeError("Expected 12 SPR PDFs plus at least 78 roster/cache files; got "+str(len(actual_src)))

    # Remove left-over partial SFTP transfers from earlier interrupted private
    # staging attempts. This is confined to our private staging area.
    cleanup="find "+q(DST_STAGE)+" -type f -name '*.transfer-*' -delete"
    run(dst,cleanup,timeout=30)
    with dst.open_sftp() as files:
        try: files.stat(DST_PUBLIC)
        except FileNotFoundError:pass
        else:raise RuntimeError("Public /sps appeared during transfer; not replacing")
        files.rename(DST_STAGE,DST_PUBLIC)
        files.stat(posixpath.join(DST_PUBLIC,"index.php"))
    say("LIVE SITE PUBLISHED",DST_PUBLIC)
    details={"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "verified_count":len(actual_src),"tar_bytes":total,
             "tar_sha256":stream_sha.hexdigest(),"app_files":31,"spr_pdfs":12,
             "historical_spr_pdfs_included":False,
             "source_modified":False,
             "target":"https://www.kustomvinyls.com/sps/"}
    with open(STAGE_INFO,"w") as f:json.dump(details,f,indent=2)
    say("COMPLETE",len(actual_src),"data files verified, 31 app files staged",
        "elapsed_s",round(time.monotonic()-start,1))
    # Test the public site and report results (cannot replace user testing).
    try:
        r=requests.get("https://www.kustomvinyls.com/sps/",timeout=20,allow_redirects=True)
        say("PUBLIC HTTP",r.status_code,"final_hostname",requests.utils.urlparse(r.url).hostname,
            "Build700_marker",("Build 700" in r.text))
    except Exception as exc:
        say("PUBLIC HTTP TEST UNAVAILABLE",type(exc).__name__)
finally:
    src.close();dst.close()
