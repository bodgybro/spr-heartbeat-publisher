#!/usr/bin/env python3
"""Regression of independent SQLite dual-host importer dispatch, no network."""
import importlib.util,io,contextlib,types,tempfile,pathlib,ast
from pathlib import Path
name=Path(__file__).resolve().parents[1]/"bodgy_spr_db_parallel_import_patch_20261123.py"
spec=importlib.util.spec_from_file_location("patch",name)
patch=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)
fixture="""import threading
# KUSTOM_DATED_SPR_SQLITE_20261120_V1
db_calls=[]
def _spr_direct_index_one(job):
 return job
def _spr_db_kustom_scheduled_retry():
 return
def _spr_db_kustom_remote(args):
 db_calls.append(('k',tuple(args)))
 return True
def _spr_direct_primary_sftp():
 return mock_primary()
if __name__=='__main__':
 pass
"""
class Channel:
 def settimeout(self,n):assert n==180
 def recv_exit_status(self):return 0
class Stdout:
 channel=Channel()
 def read(self,n):assert n==4000;return b'SPR_DB_ONE date=2026-11-23 driver ok\n'
 def close(self):pass
class Std:
 def close(self):pass
class SSH:
 def __init__(self):self.closed=False
 def exec_command(self,command,timeout):
  assert timeout==30
  assert command.startswith('/usr/local/bin/php -d max_execution_time=0 /home11/bodgybro/sps-private-assets/spr-db-v1/spr-db-v1-import.php ')
  assert 'kustomvi' not in command
  commands.append(command)
  return Std(),Stdout(),Std()
 def close(self):self.closed=True
class SFTP:
 def close(self):pass
commands=[]
def mock_primary():
 return SSH(),SFTP(),'/home11/bodgybro/public_html/sps'
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'generated.py'
 p.write_text(fixture)
 patch.apply(p)
 updated=p.read_text()
 assert patch.MARKER in updated
 ast.parse(updated)
 patch.apply(p)
 assert updated==p.read_text()
 namespace={'__name__':'isolated','mock_primary':mock_primary}
 with contextlib.redirect_stdout(io.StringIO()) as logs:
  exec(compile(updated,str(p),'exec'),namespace)
  for options in (['--jobs'],['--scan','3'],['--one','2026-11-23','driver'],['--one','2026-11-23','guard']):
   result=namespace['_spr_db_kustom_remote'](options)
   assert result is True
  for options in (['--one','bad','driver'],['--one','2026-11-23','hack'],['--scan','200'],['--foo']):
   try:namespace['_spr_db_bodgy_remote'](options)
   except ValueError:pass
   else:raise AssertionError('Invalid parameters accepted')
 assert len(commands)==4 and len(namespace['db_calls'])==4
 assert 'BODGY SPR DB' in logs.getvalue()
 assert all('/home11/bodgybro/' in c for c in commands)
 # An independent import failure doesn't invalidate the Kustom or SPR upload.
 namespace['_spr_db_bodgy_remote']=lambda args: (_ for _ in ()).throw(RuntimeError('unavailable'))
 assert namespace['_spr_db_kustom_remote'](['--jobs']) is True
 assert namespace['db_calls'][-1][0]=='k'
 # Kustom failure still attempts Bodgybros.
 calls=[]
 namespace['_spr_db_bodgy_remote']=lambda args:calls.append(tuple(args))
 namespace['_SPR_DB_KUSTOM_IMPORT_ORIGINAL']=lambda args: (_ for _ in ()).throw(RuntimeError('kustom unavailable'))
 try:namespace['_spr_db_kustom_remote'](['--jobs'])
 except RuntimeError as exc:assert str(exc)=='kustom unavailable'
 else:raise AssertionError('Kustom failure was swallowed')
 assert calls==[('--jobs',)]
print('BODGY_SPR_DB_PARALLEL_IMPORT_ALL_TESTS_PASS Kustom_retained=yes Bodgy_independent=yes hourly_retry=yes invalid_commands_blocked=yes')
