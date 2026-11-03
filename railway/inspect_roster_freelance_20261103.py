#!/usr/bin/env python3
"""Read-only check of live Build700 freelancer search and Blacktown roster source."""
import os,io,base64,posixpath,re,stat,json
from pathlib import Path
import paramiko
from pypdf import PdfReader
def out(*a):print("[FREELANCE INSPECT]",*a,flush=True)
def key_from_env():
    k=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode("utf8")
    for typ in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:return typ.from_private_key(io.StringIO(k))
        except Exception:pass
    raise RuntimeError("Could not load source SFTP key")
cli=paramiko.SSHClient()
cli.load_host_keys("/data/credentials/spr-sftp-known_hosts")
cli.set_missing_host_key_policy(paramiko.RejectPolicy())
cli.connect(hostname=os.environ["SFTP_HOST"],username=os.environ["SFTP_USERNAME"],
            port=int(os.environ.get("SFTP_PORT") or 22),
            pkey=key_from_env(),look_for_keys=False,allow_agent=False,timeout=12)
root=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
if root.endswith("/sps/spr"):root=root[:-4]
elif root.endswith("/public_html"):root+="/sps"
if not root.endswith("/sps"):raise RuntimeError("Unexpected source root")
try:
 with cli.open_sftp() as sftp:
    files=sftp.listdir_attr(root)
    scripts=[x.filename for x in files if x.filename.endswith(".js") and x.filename.startswith("script")]
    out("Root JS filenames",scripts[:24],"count",len(scripts))
    for n in ("index.php","index.html"):
        with sftp.open(posixpath.join(root,n),"rb") as f:body=f.read().decode("utf8",errors="replace")
        found=re.findall(r"script[^\"']{0,120}\.js",body)
        out(n,"script src",found[:8])
    latest=["script-700-fromto-locations-v1.js","script.js"]
    for name in latest:
        remote=posixpath.join(root,name)
        try:
            with sftp.open(remote,"rb") as f:code=f.read().decode("utf8",errors="replace")
        except Exception as ex:
            out(name,"unavailable",type(ex).__name__);continue
        out("JS",name,"size",len(code),"freelance count",len(re.findall("freelance",code,re.I)))
        if name!=latest[0]:continue
        lines=code.splitlines()
        markers=[(i,line) for i,line in enumerate(lines) if re.search(r"roster(Search|Render|Find|Scan|Specific)|Freelance|specific.*search|search.*specific|roster.*shift",line,re.I)]
        out("RELEVANT SOURCE LINES",len(markers))
        for idx,line in markers[:125]:
            start=max(0,idx-4);end=min(len(lines),idx+5)
            content="\n".join(f"{j+1}: {lines[j]}" for j in range(start,end))
            out("SRC",idx+1,content[:1100])
    manifest=posixpath.join(root,".roster-cache","manifest.json")
    with sftp.open(manifest,"rb") as f: m=json.loads(f.read())
    filtered=[{k:e.get(k) for k in ("name","cache_path","kind","url")} for e in m.get("entries",[])
              if e.get("kind")=="pdf" and "blacktown" in str(e.get("cache_path","")).lower() and
              any(w in str(e.get("cache_path","")).lower() for w in ("period","daily"))]
    out("Blacktown relevant manifest",filtered[:15])
    for e in filtered:
        path=posixpath.join(root,"rosters",e["cache_path"])
        try:
            with sftp.open(path,"rb") as f:
                f.prefetch(max_concurrent_requests=24)
                data=f.read()
            pdf=PdfReader(io.BytesIO(data),strict=False)
            out("PDF",e["cache_path"],"bytes",len(data),"pages",len(pdf.pages))
            for p,page in enumerate(pdf.pages):
                txt=page.extract_text(extraction_mode="layout") or ""
                all_lines=txt.splitlines()
                hits=[i for i,t in enumerate(all_lines) if
                      re.search(r"morgan,\s*shane|sachdeva,\s*jitin|freelance cross|freelance",t,re.I)]
                if not hits:continue
                out("PDFMATCH",e["cache_path"],"page",p+1,"hitCount",len(hits))
                for index in hits[:5]:
                    out("PDFCTX","page",p+1,"line",index+1,"/".join(x.strip()[:180] for x in all_lines[max(0,index-2):min(len(all_lines),index+4)]))
        except Exception as ex:
            out("PDF ERROR",e["cache_path"],type(ex).__name__,str(ex)[:160])
finally:cli.close()
