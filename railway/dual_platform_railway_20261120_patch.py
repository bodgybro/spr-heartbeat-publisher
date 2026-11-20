#!/usr/bin/env python3
"""Extend the existing Railway SPR/roster updater with identical two-site
platform timetable checks. No GitHub schedules and no cPanel cron required.
Apply after all other updater source patches, before py_compile/start.sh.
"""
import ast
from pathlib import Path
import sys

MARKER = "# SPR_DUAL_PLATFORM_RAILWAY_20261120_V1"
ANCHOR = "    threading.Thread(target=auto_update_scheduler,daemon=True).start()"
MAIN = 'if __name__=="__main__":'
EXTENSION = r'''
# SPR_DUAL_PLATFORM_RAILWAY_20261120_V1
# This scheduler deliberately does not change the 08/12/16/22 SPR/roster slots.
# Both sites execute the exact same proven private PHP worker at 03/04/05 Sydney.
# The worker enforces a single valid refresh per Sydney date and keeps rollback.
def _platform_railway_site_command(side, mode):
    path_b='/home11/bodgybro/sps-private-assets/platform-auto-refresh.php'
    path_k='/home10/kustomvi/sps-private-assets/platform-auto-refresh.php'
    path = path_b if side=='bodgybros' else path_k
    expected='2ef90d126988998bef57fd08e43ae83c541983da40d7387b54c0f52f124dafde'
    if side not in ('bodgybros','kustomvinyls') or mode not in ('--check','--cron'):
        raise ValueError('Invalid site or platform command')
    ssh=ftp=None
    try:
        if side=='bodgybros':
            ssh,ftp,_=_roster_sftp_connection()
        else:
            ssh,ftp=_dual_kustom_open()
        # Confirm each installation remains the same reviewed script before running it.
        stdin,stdout,stderr=ssh.exec_command('sha256sum '+path,timeout=25)
        digest_output=stdout.read().decode('ascii','replace').strip()
        digest_rc=stdout.channel.recv_exit_status()
        digest=digest_output.split()[0] if digest_output else ''
        if digest_rc!=0 or digest!=expected:
            raise RuntimeError('private platform script differs from verified shared version')
        stdin,stdout,stderr=ssh.exec_command('/usr/local/bin/php '+path+' '+mode,timeout=600)
        out=stdout.read(8000).decode('utf-8','replace')
        err=stderr.read(3000).decode('utf-8','replace')
        status=stdout.channel.recv_exit_status()
        if status!=0:
            # Never publish raw remote stderr or account internals to logs.
            raise RuntimeError('private PHP worker exited '+str(status))
        # Source-defined status text is safe: no credentials or timetable payload.
        if mode=='--check':
            matches=[l for l in out.splitlines() if l.startswith('PLATFORM_AUTO_CHECK_PASS')]
            if len(matches)!=1:
                raise RuntimeError('unexpected platform check response')
            print('[PLATFORM RAILWAY VERIFY] '+side+' '+matches[0][:220],flush=True)
        else:
            completed='PLATFORM_AUTO_REFRESH_OK' in out
            print('[PLATFORM RAILWAY RUN] '+side+
                  (' refresh completed' if completed else ' already-current / outside permitted window'),flush=True)
        return True
    finally:
        if ftp is not None:
            try:ftp.close()
            except Exception:pass
        if ssh is not None:
            try:ssh.close()
            except Exception:pass

def _platform_railway_two_site_scheduler():
    import time as _platform_time
    from datetime import datetime as _platform_datetime
    from zoneinfo import ZoneInfo as _platform_ZoneInfo
    zone=_platform_ZoneInfo('Australia/Sydney')
    # Verify both hosting connections and the identical PHP script on startup.
    for side in ('bodgybros','kustomvinyls'):
        try:
            _platform_railway_site_command(side,'--check')
        except Exception as exc:
            print('[PLATFORM RAILWAY VERIFY FAILED] '+side+' '+type(exc).__name__+
                  ': '+str(exc)[:125],flush=True)
    print('[PLATFORM RAILWAY READY] two sites, Sydney 03:07/04:07/05:07 hourly retries; '
          'existing SPR and ROC jobs unchanged',flush=True)
    while True:
        now=_platform_datetime.now(zone)
        # The original cPanel worker is safe to call once within each hour;
        # it checks its own Sydney clock and never overwrites a valid same-day index.
        if 3 <= now.hour <= 5 and now.minute >= 7:
            slot=now.strftime('%Y-%m-%d-%H')
            marker=DATA_ROOT/('.platform-railway-dual-'+slot+'.attempted')
            try:
                # Durable per-hour guard survives Railway restarts.
                with marker.open('x',encoding='ascii') as f:
                    f.write(now.isoformat()+'\n')
            except FileExistsError:
                pass
            except Exception as exc:
                print('[PLATFORM RAILWAY MARKER FAILED] '+type(exc).__name__,flush=True)
            else:
                for side in ('bodgybros','kustomvinyls'):
                    try:
                        _platform_railway_site_command(side,'--cron')
                    except Exception as exc:
                        print('[PLATFORM RAILWAY RUN FAILED] '+side+' '+
                              type(exc).__name__+': '+str(exc)[:130],flush=True)
        _platform_time.sleep(30)
'''

def apply(path):
    source=path.read_text(encoding='utf-8')
    if MARKER in source:
        print('[PLATFORM RAILWAY] already installed',flush=True)
        return
    if source.count(ANCHOR)!=1 or source.count(MAIN)!=1:
        raise RuntimeError('Unexpected updater scheduler/main; no changes made')
    if ('def _roster_sftp_connection(' not in source or
        'def _dual_kustom_open(' not in source or
        'AUTO_RUN_TIMES = [(8,0),(12,0),(16,0),(22,0)]' not in source):
        raise RuntimeError('Existing two-site connections or four-slot schedule not verified')
    updated=source.replace(MAIN,EXTENSION+'\n'+MAIN,1)
    updated=updated.replace(ANCHOR,ANCHOR+'\n    threading.Thread(target=_platform_railway_two_site_scheduler,daemon=True,name="platform-two-sites").start()',1)
    ast.parse(updated)
    compile(updated,str(path),'exec')
    path.write_text(updated,encoding='utf-8')
    print('[PLATFORM RAILWAY PATCH READY] both sites share the same scheduler/worker; SPR and ROC unchanged',flush=True)

if __name__=='__main__':
    if len(sys.argv)!=2:
        raise SystemExit('Usage: dual-platform-patch.py /app/spr_online_updater.py')
    apply(Path(sys.argv[1]))
