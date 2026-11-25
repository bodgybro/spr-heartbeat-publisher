#!/usr/bin/env python3
"""No-network test of the new index hook using the actual archive patch."""
from pathlib import Path
import importlib.util,tempfile
here=Path(__file__).parent
def load(name):
    spec=importlib.util.spec_from_file_location(name,here/(name+".py"))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
archive=load("roster_fortnight_private_archive_20261123_patch")
index=load("claim_roster_sqlite_auto_20261125_patch")
base="""# DUAL_SITE_SFTP VERIFIED
def _roster_valid_cache_path(path):return path.split("/")
def _spr_direct_primary_sftp():return SSH("bodgybros"),FTP(),"/home11/bodgybro/public_html/sps"
def _dual_kustom_open():return SSH("kustomvinyls"),FTP()
_DUAL_KUSTOM_ROOT="/home10/kustomvi/public_html/sps"
def upload_cached_roster_pdf(url,name,data,cache_path=""):
    published.append(cache_path)
    return "ORIGINAL_UPLOAD_SUCCESS"
if __name__=="__main__":pass
"""
class SSH:
    def __init__(self,site):self.site=site
    def close(self):pass
class FTP:
    def close(self):pass
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)/"updater.py";p.write_text(base)
    archive.apply(p);index.apply(p)
    src=p.read_text();index.apply(p);assert p.read_text()==src
    published=[];archived=[];indexed=[]
    env={"__name__":"isolated","SSH":SSH,"FTP":FTP,"published":published}
    exec(compile(src,str(p),"exec"),env)
    env["_roster_history_fortnight"]=lambda data:"2026-11-15"
    env["_roster_history_remote_copy"]=lambda ssh,*args:archived.append(ssh.site) or "saved"
    def ix(ssh,public,private,cache_path,data,digest,cache):
        assert ssh.site in archived
        assert data.startswith(b"%PDF-")
        assert private.endswith("/roster-fortnights-v1")
        assert cache_path=="central/drivers/period/CEN-D-PER.pdf"
        assert len(digest)==64
        indexed.append(ssh.site)
        if ssh.site=="bodgybros":raise RuntimeError("simulate unavailable index")
        return "indexed"
    env["_cc_roster_index_after_archive"]=ix
    result=env["upload_cached_roster_pdf"]("source","CEN-D-PER.pdf",b"%PDF-fake","central/drivers/period/CEN-D-PER.pdf")
    assert result=="ORIGINAL_UPLOAD_SUCCESS"
    assert published==["central/drivers/period/CEN-D-PER.pdf"]
    assert archived==indexed==["bodgybros","kustomvinyls"]
print("ROSTER_SQLITE_AUTO_TEST_PASS verified_archive_first=yes both_sites=yes failure_nonfatal=yes original_upload_preserved=yes")
