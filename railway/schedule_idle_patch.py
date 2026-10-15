#!/usr/bin/env python3
"""Run after existing Railway Cloudflare/fast-roster patches."""
import ast
import sys
from pathlib import Path

SCHEDULER = '''def auto_update_scheduler():
    """Run only at 10:00, 14:00, 20:00 Sydney time; never catch up hours late."""
    print("Automatic SPR + roster updates: 10:00, 14:00, 20:00 Australia/Sydney.", flush=True)
    while True:
        try:
            now = datetime.now()
            today = now.date().isoformat()
            minute = now.hour * 60 + now.minute
            for h, m in AUTO_RUN_TIMES:
                # Two-minute tolerance for process startup/scheduler jitter.
                if not (h * 60 + m <= minute < h * 60 + m + 2):
                    continue
                slot = f"{today} {h:02d}:{m:02d}"
                completed = {v for v in _load_completed_auto_slots() if v.startswith(today + " ")}
                if slot in completed:
                    continue
                site = scheduler_site_url()
                if not site:
                    print(f"Scheduled {slot} skipped: no SPR site URL", flush=True)
                elif _job_snapshot().get("running"):
                    print(f"Scheduled {slot} skipped: update already running", flush=True)
                elif start_background_update(site):
                    print(f"Scheduled {slot} SPR + roster update started", flush=True)
                else:
                    print(f"Scheduled {slot} skipped: updater busy", flush=True)
                completed.add(slot)
                _save_completed_auto_slots(completed)
        except Exception as e:
            print("Automatic update scheduler error:", e, flush=True)
        time.sleep(20)
'''


def replace_func(source, name, edit):
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(nodes) != 1:
        raise RuntimeError('Expected one function: ' + name)
    n = nodes[0]
    lines = source.splitlines(keepends=True)
    block = ''.join(lines[n.lineno-1:n.end_lineno])
    updated = edit(block)
    return ''.join(lines[:n.lineno-1]) + updated.rstrip() + '\n' + ''.join(lines[n.end_lineno:])


def replace_exact(old, new):
    def edit(block):
        if block.count(old) != 1:
            raise RuntimeError('Unexpected updater source: ' + old)
        return block.replace(old, new, 1)
    return edit


def apply(path):
    source = path.read_text(encoding='utf-8')
    if '# OPTIMIZED_SPR_SCHEDULE_10_14_20' in source:
        print('Optimisation already installed')
        return
    old = 'AUTO_RUN_TIMES = [(0,0),(8,0),(12,0),(16,0),(20,0)]'
    if source.count(old) != 1:
        raise RuntimeError('Unexpected AUTO_RUN_TIMES; no changes made')
    source = source.replace(old, 'AUTO_RUN_TIMES = [(10,0),(14,0),(20,0)]', 1)
    source = replace_func(source, 'auto_update_scheduler', lambda _: SCHEDULER)
    source = replace_func(source, 'online_control_worker', replace_exact('        time.sleep(5)', '        time.sleep(5 if active_trigger else 15)'))
    source = replace_func(source, 'publish_updater_status', replace_exact('["00:00","08:00","12:00","16:00","20:00"]', '["10:00","14:00","20:00"]'))
    source = replace_func(source, 'updater_status_heartbeat_worker', replace_exact('time.sleep(20 if active else 60)', 'time.sleep(20 if active else 120)'))
    source = '# OPTIMIZED_SPR_SCHEDULE_10_14_20\n' + source
    compile(source, str(path), 'exec')
    path.write_text(source, encoding='utf-8')
    print('Schedule 10:00/14:00/20:00 Sydney; idle command polling 15s; idle heartbeat 120s')


if __name__ == '__main__':
    apply(Path(sys.argv[1]))
