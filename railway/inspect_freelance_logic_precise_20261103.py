#!/usr/bin/env python3
"""Read-only targeted JavaScript source extraction for Build700 specific freelance search."""
import os,io,base64,paramiko,posixpath,re
from collections import defaultdict
raw=base64.b64decode(os.environ["SFTP_PRIVATE_KEY_B64"]).decode()
key=None
for cls in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
    try:key=cls.from_private_key(io.StringIO(raw));break
    except:pass
cli=paramiko.SSHClient()
cli.load_host_keys("/data/credentials/spr-sftp-known_hosts")
cli.set_missing_host_key_policy(paramiko.RejectPolicy())
cli.connect(hostname=os.environ["SFTP_HOST"],username=os.environ["SFTP_USERNAME"],
 port=int(os.environ.get("SFTP_PORT") or 22),pkey=key,timeout=12,
 allow_agent=False,look_for_keys=False)
root=os.environ["SFTP_ROOT"].replace("\\","/").rstrip("/")
if root.endswith("/sps/spr"):root=root[:-4]
elif root.endswith("/public_html"):root+="/sps"
try:
 with cli.open_sftp() as ftp:
    with ftp.open(posixpath.join(root,"script-700-fromto-locations-v1.js"),"rb") as f:
        f.prefetch(max_concurrent_requests=32)
        js=f.read().decode("utf8",errors="replace")
    lines=js.splitlines()
    def out(*args):print("[FREELANCE SOURCE]",*args,flush=True)
    out("TOTAL",len(lines),len(js))
    terms=[
      r"freelance",r"rosterAdvancedUi\.specific",r"rosterSpecific",
      r"function rosterSearch",r"async function rosterSearch",
      r"specificSearch",r"specificTag",r"rosterSearch.*Specific",r"specificDate",
      r"roster[A-Za-z]*(?:Name|Row|Crew|Duty|Time|Match|Search|Result)",
      r"roster[A-Za-z]*(?:Full|Date|Cells|Scan)",
      r"selectedSpecific",r"specificSelect",r"searchSpecific",
      r"Specific|Freelance"
    ]
    for term in terms:
        positions=[i for i,line in enumerate(lines) if re.search(term,line,re.I)]
        out("TERM",term,"hits",len(positions),"lines",positions[:45])
    functions=[(i+1,m.group(1)) for i,line in enumerate(lines)
               if (m:=re.search(r"^\s*(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\(",line))]
    out("FUNCTION NAMES",[(line,name) for line,name in functions if
              re.search(r"roster|search|specific|freelance",name,re.I)][:190])
    important=[
      i for i,line in enumerate(lines) if re.search(
       r"freelance|specific.*search|search.*specific|rosterAdvancedUi\.specific|"
       r"roster[A-Za-z]*(?:SearchSpecific|SpecificSearch|SearchAdvanced|AdvancedSearch|SearchRoster|RenderResults)|"
       r"rosterSearchSpecific|specificTag|specificDate",line,re.I)
    ]
    out("TARGET_LINES",important[:90])
    sections=[]
    for i in important:
        start=max(0,i-13);end=min(len(lines),i+19)
        if sections and start<=sections[-1][1]+8:
            sections[-1]=(sections[-1][0],max(sections[-1][1],end))
        else:sections.append((start,end))
    for start,end in sections[:16]:
        out("BLOCK",start+1,end,"LINES")
        content="\n".join(f"{i+1} {lines[i]}" for i in range(start,end))
        for offset in range(0,min(len(content),19000),4000):
            out("CODE",start+1,"part",offset//4000,content[offset:offset+4000])
finally:cli.close()
