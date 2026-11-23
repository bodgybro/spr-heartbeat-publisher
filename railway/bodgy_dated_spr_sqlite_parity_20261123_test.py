#!/usr/bin/env python3
"""Runtime regression tests for independent Bodgybros dated-SPR importer patch."""
from pathlib import Path
import tempfile,ast,types,threading
import sys
sys.path.insert(0,str(Path(__file__).parent))
from bodgy_dated_spr_sqlite_parity_20261123_patch import apply,MARKER
BASE='''import threading
# KUSTOM_DATED_SPR_SQLITE_20261120_V1
calls=[]
def _spr_db_kustom_remote(args):calls.append(("kustom",args))
def _spr_db_kustom_scheduled_retry():pass
def _spr_direct_primary_sftp():
    calls.append(("open","bodgy"))
    return ssh,ftp,"/home11/bodgybro/public_html/sps"
def _spr_direct_index_one(job):
    calls.append(("verified_source",job))
    _spr_db_kustom_remote(("--one",job["date"],job["role"]))
    return "indexed"
if __name__=="__main__":
    pass
'''
class Stream:
    def __init__(self,value):
        self.value=value
        self.channel=types.SimpleNamespace(settimeout=lambda v:None,recv_exit_status=lambda:0)
    def read(self,n=-1):return self.value.encode()
    def close(self):pass
class SSH:
    def exec_command(self,cmd,timeout):
        assert cmd.startswith("/usr/local/bin/php -d max_execution_time=0 /home11/bodgybro/sps-private-assets/spr-db-v1/spr-db-v1-import.php ")
        assert timeout==30
        commands.append(cmd)
        return Stream(""),Stream("SPR_DB_ONE imported date role"),Stream("")
    def close(self):stops.append("ssh")
class FTP:
    def close(self):stops.append("ftp")
class FakeThread:
    def __init__(self,target,daemon,name):
        assert daemon and name=="bodgy-dated-spr-db"
        self.target=target
    def start(self):starts.append("started")
commands=[];stops=[];starts=[]
with tempfile.TemporaryDirectory() as tmp:
    target=Path(tmp)/"updater.py"
    target.write_text(BASE)
    apply(target)
    result=target.read_text()
    assert result.count(MARKER)==1
    assert "def _spr_db_bodgy_remote(args):" in result
    assert "_SPR_DB_UPSTREAM_DATE_INDEXER=_spr_direct_index_one" in result
    assert "threading.Thread(target=_spr_db_bodgy_scheduled_retry," in result
    compile(result,str(target),"exec");ast.parse(result)
    apply(target)
    assert target.read_text()==result,"Idempotent patch should not modify live code twice"
    fake_thread=types.SimpleNamespace(Thread=FakeThread)
    scope={"__name__":"updater-test","threading":fake_thread,"ssh":SSH(),"ftp":FTP()}
    exec(compile(result,str(target),"exec"),scope)
    assert starts==["started"]
    job={"date":"2026-11-23","role":"driver"}
    assert scope["_spr_direct_index_one"](job)=="indexed"
    assert scope["calls"]==[("verified_source",job),
      ("kustom",("--one","2026-11-23","driver")),("open","bodgy")]
    assert commands==["/usr/local/bin/php -d max_execution_time=0 /home11/bodgybro/sps-private-assets/spr-db-v1/spr-db-v1-import.php --one 2026-11-23 driver"]
    assert stops==["ftp","ssh"]
    assert scope["_spr_db_bodgy_remote"](("--jobs",))
    assert scope["_spr_db_bodgy_remote"](("--scan","3"))
    assert len(commands)==3
    for malformed in (("--one","2026-11-23","g\x00uard"),("--scan","99"),("--reprocess","2026-11-23","driver"),("../oops",)):
        try:scope["_spr_db_bodgy_remote"](malformed)
        except ValueError:pass
        else:raise AssertionError("Unsafe remote command accepted "+repr(malformed))
    scope["_spr_direct_index_one"]({"role":"guard"})
    assert len(commands)==3, "No import should run when no real date available"
    print("BODGY_DATED_SPR_DB_RUNTIME_TESTS_PASS source_before_db=yes kustom_before_bodgy=yes both_sites_independent=yes hourly_thread=yes safety_whitelist=yes idempotent=yes")
