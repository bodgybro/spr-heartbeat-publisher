#!/usr/bin/env python3
"""Test Sunday fortnight parsing and dual private archival without network."""
from pathlib import Path
import tempfile,importlib.util,io,datetime,contextlib
from reportlab.pdfgen import canvas
import sys
spec=importlib.util.spec_from_file_location("archive_patch",str(Path(__file__).with_name("roster_fortnight_private_archive_20261123_patch.py")))
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
BASE="""
# DUAL_SITE_SFTP VERIFIED
saved=[]
def _roster_valid_cache_path(path):return path.split("/")
def _spr_direct_primary_sftp():return MockSSH("bodgy"),MockFTP(),"/home11/bodgybro/public_html/sps"
def _dual_kustom_open():return MockSSH("kustom"),MockFTP()
_DUAL_KUSTOM_ROOT="/home10/kustomvi/public_html/sps"
def upload_cached_roster_pdf(url,name,data,cache_path=""):
    saved.append((url,name,cache_path))
    return "ORIGINAL_UPLOAD_SUCCESS"
if __name__=="__main__":pass
"""
def pdf_for(dates,meta=None):
    buf=io.BytesIO()
    p=canvas.Canvas(buf,pagesize=(800,650))
    p.setFont("Helvetica",12)
    if meta:
        p.drawString(20,640,"Published "+meta)
    for i,d in enumerate(dates):
        p.drawString(12,610-i*29,d.strftime("%d/%m/%Y"))
    p.showPage();p.save()
    return buf.getvalue()
def dates(start,count):
    return [start+datetime.timedelta(days=i) for i in range(count)]
class FakeChannel:
    def settimeout(self,seconds):assert seconds==120
    def recv_exit_status(self):return 0
class FakeStream:
    def __init__(self,val):self.value=val.encode();self.channel=FakeChannel()
    def read(self,size):return self.value[:size]
    def close(self):pass
class MockSSH:
    def __init__(self,site):self.site=site
    def exec_command(self,script,timeout=0):
        assert timeout==45
        assert "sha256sum -c -" in script
        assert "install -d -m 700 " in script
        assert "sps-private-assets/roster-fortnights-v1" in script
        assert "public_html/sps/rosters/" in script
        assert not any(t in script for t in ("../","| rm ",";rm ","/tmp/spr"))
        assert "/2026-11-15/" in script
        calls.append(self.site)
        return FakeStream(""),FakeStream("ROSTER_ARCHIVE_SAVED\n"),FakeStream("")
    def close(self):pass
class MockFTP:
    def close(self):pass

base=datetime.date(2026,11,15)
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/"updater.py"
    path.write_text(BASE)
    module.apply(path)
    src=path.read_text()
    assert src.count(module.MARKER)==1
    module.apply(path)
    assert path.read_text()==src
    env={"__name__":"isolated","MockSSH":MockSSH,"MockFTP":MockFTP}
    exec(compile(src,str(path),"exec"),env)
    detect=env["_roster_history_fortnight"]
    assert detect(pdf_for(dates(base,14),"23/11/2026"))=="2026-11-15"
    assert detect(pdf_for(dates(base+datetime.timedelta(days=1),12),"11/11/2026"))=="2026-11-15"
    assert detect(pdf_for(dates(base+datetime.timedelta(days=14),14),"27/11/2026"))=="2026-11-29"
    assert detect(pdf_for(dates(base,13)))=="2026-11-15"
    for invalid in (pdf_for(dates(base,6)),b"random",pdf_for([])):
        try:detect(invalid)
        except ValueError:pass
        else:raise AssertionError("Unreliable PDF accepted")
    validate=env["_roster_history_safe_path"]
    assert validate("central/drivers/daily/CEN-D-DAY.pdf")
    assert validate("blacktown/guards/period/BLA-G-PER.pdf")
    assert validate("northsydney/drivers/fortnight/NOS-D-NFR.pdf")
    for invalid in ("../central/drivers/daily/CEN-D-DAY.pdf",
        "central/both/daily/CEN-D-DAY.pdf",
        "central/drivers/daily/../CEN-D-DAY.pdf",
        "/central/drivers/daily/CEN-D-DAY.pdf",
        "central/drivers/daily/evil.pdf;touch"):
        try:validate(invalid)
        except ValueError:pass
        else:raise AssertionError("Unsafe path accepted "+invalid)
    calls=[]
    raw=pdf_for(dates(base,14),"23/11/2026")
    env["calls"]=calls
    result=env["upload_cached_roster_pdf"]("https://source","CEN-D-DAY.pdf",raw,"central/drivers/daily/CEN-D-DAY.pdf")
    assert result=="ORIGINAL_UPLOAD_SUCCESS"
    assert calls==["bodgy","kustom"],calls
    assert len(env["saved"])==1
    assert env["_ROSTER_HISTORY_BASE_B"].startswith("/home11/bodgybro/sps-private-assets/")
    assert env["_ROSTER_HISTORY_BASE_K"].startswith("/home10/kustomvi/sps-private-assets/")
print("FORTNIGHT_ARCHIVER_TESTS_PASS current_15Nov=yes next_29Nov=yes period_start_Monday=yes private_dual_site=yes safe_paths=yes original_upload_preserved=yes")
