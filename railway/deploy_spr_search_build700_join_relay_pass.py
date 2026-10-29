#!/usr/bin/env python3
"""One-time Build 700 Relay/Join PASS display correction using verified live files.
No changes to original PDFs, indexed search data, roster PDFs, updater, auth or RC1.
"""
import base64,hashlib,io,os,posixpath,re
import paramiko

EXPECTED={
  'script.js':'9644c4036cb18107',
  'index.php':'c588261a8deaa2a0',
  'index.html':'4e6f8bdf678845d7',
}
OLD_REF='script.js?v=700'
NEW_REF='script.js?v=700-relay-pass'
NEAR_ROUTE="""  // Normal relayed-by layout: one complete location per source row.
  // Shift 335 is: "Bondi Jctn Sdgs TRML" then "Central ESR".
"""
ROUTE_FIX=r"""  // Build 700: in a Join-rear-end relay the join instruction and its
  // '@ location' are NOT the PASS route. Use the actual journey heading.
  if(routeRows.some(row=>/^Join rear end\b/i.test(row.text))){
    const movementRows=routeRows.filter(row=>
      !/^Join rear end\b/i.test(row.text)&&!/^@\s*/.test(row.text));
    for(let k=movementRows.length-1;k>=0;k--){
      const route=splitKnownPassRouteHeading(movementRows[k].text,lines,start,index);
      if(route)return route;
    }
    if(movementRows.length>=2){
      const origin=movementRows[movementRows.length-2].text;
      const destination=movementRows[movementRows.length-1].text;
      const known=knownPassRouteLocationKeys(lines,start,index);
      if(known.has(stationName(origin))&&known.has(stationName(destination)))
        return origin+' -> '+destination;
    }
  }

"""
JOIN_REPLACEMENT=r"""    const joinedRearRelay=Boolean(relay?.joinText&&item.entry.relayedBy);
    // The join location and incoming shift identify this movement already.
    // Do not repeat "Join rear end" or show the same shift twice as "Relay".
    const join=joinedRearRelay
      ?(relay.location?'<div class="secondary">Location: '+esc(relay.location)+'</div>':'')
      :relay?.joinText?'<div class="duty-title">'+esc(relay.joinText)+'</div>'+(relay.location?'<div class="secondary">Location: '+esc(relay.location)+'</div>':''):'';
"""
def sha(data):return hashlib.sha256(data).hexdigest()
def read(ftp,p):
    with ftp.open(p,'rb') as handle:return handle.read()
def put(ftp,p,data):
    with ftp.open(p,'wb') as handle:handle.write(data)
def remote_root():
    root=os.environ['SFTP_ROOT'].replace('\\','/').rstrip('/')
    if root.endswith('/sps/spr'):return root[:-4]
    if root.endswith('/sps'):return root
    if root.endswith('/public_html') or root=='public_html':return root+'/sps'
    raise RuntimeError('Unrecognised web root; refusing deployment')
def patch_js(src):
    if src.count(NEAR_ROUTE)!=1:raise RuntimeError('Route extractor shape changed')
    if "function sprOriginalPdfMatchesIndex(" not in src or 'function scheduleRetainedSprRestore()' not in src:
        raise RuntimeError('Tested Build 700 fast-loading and last-SPR safeguards missing')
    src=src.replace(NEAR_ROUTE,ROUTE_FIX+NEAR_ROUTE,1)
    matches=re.findall(r'(?m)^    const join=relay\?\.joinText\?.*$',src)
    if len(matches)!=1:raise RuntimeError('Expected exactly one Join relay formatter')
    src=src.replace(matches[0],JOIN_REPLACEMENT.rstrip(),1)
    old='$'+'{passCrew}'+'$'+'{renderRelayDetails(relay)}</div>'
    new='$'+'{passCrew}'+'$'+"{joinedRearRelay?'':renderRelayDetails(relay)}</div>"
    if src.count(old)!=1:raise RuntimeError('Expected exactly one PASS Relay tail')
    return src.replace(old,new,1)
def patch_html(src,name):
    if src.count('class="build-number">Build 700')!=1:
        raise RuntimeError(name+' Build 700 label missing')
    if src.count(OLD_REF)!=1:raise RuntimeError(name+' browser JS cache reference changed')
    return src.replace(OLD_REF,NEW_REF,1)
def main():
    raw=base64.b64decode(os.environ['SFTP_PRIVATE_KEY_B64']).decode('utf-8')
    key=None
    for klass in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:key=klass.from_private_key(io.StringIO(raw));break
        except Exception:pass
    if key is None:raise RuntimeError('Existing SFTP key unavailable')
    ssh=paramiko.SSHClient()
    ssh.load_host_keys('/data/credentials/spr-sftp-known_hosts')
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(hostname=os.environ['SFTP_HOST'],username=os.environ['SFTP_USERNAME'],
      port=int(os.environ.get('SFTP_PORT') or 22),pkey=key,look_for_keys=False,
      allow_agent=False,timeout=12,auth_timeout=12,banner_timeout=12)
    ftp=ssh.open_sftp();root=remote_root()
    originals={};changed={};staged=[];replaced=[]
    try:
        for name in ('script.js','index.php','index.html'):
            original=read(ftp,posixpath.join(root,name))
            if not sha(original).startswith(EXPECTED[name]):
                raise RuntimeError('Live '+name+' checksum unexpected '+sha(original)[:16]+'; no files changed')
            originals[name]=original
            text=original.decode('utf-8')
            updated=patch_js(text) if name=='script.js' else patch_html(text,name)
            changed[name]=updated.encode('utf-8')
        # All source checks complete before touching any live files.
        for name,data in changed.items():
            dest=posixpath.join(root,name)
            temp=dest+'.b700-relay-stage-'+str(os.getpid())
            put(ftp,temp,data)
            if sha(read(ftp,temp))!=sha(data):
                raise RuntimeError('Staged checksum mismatch: '+name)
            staged.append((name,temp,dest))
        try:
            for name,temp,dest in staged:
                ftp.posix_rename(temp,dest);replaced.append(name)
                if sha(read(ftp,dest))!=sha(changed[name]):
                    raise RuntimeError('Live checksum mismatch: '+name)
                print('[BUILD 700 RELAY LIVE VERIFIED]',name,sha(changed[name])[:16],flush=True)
            print('[BUILD 700 RELAY COMPLETE] Shift 2871 PASS uses real route; join relay not duplicated. PDF/index/RC1 untouched',flush=True)
        except Exception:
            for name in reversed(replaced):
                dest=posixpath.join(root,name);temp=dest+'.b700-relay-rollback-'+str(os.getpid())
                put(ftp,temp,originals[name]);ftp.posix_rename(temp,dest)
                print('[BUILD 700 RELAY ROLLED BACK]',name,flush=True)
            raise
    finally:
        for name,temp,_ in staged:
            try:ftp.remove(temp)
            except Exception:pass
        ftp.close();ssh.close()
if __name__=='__main__':main()
