#!/usr/bin/env python3
"""Reduce only *idle* SPR updater heartbeat writes to Cloudflare KV.

Run after schedule_idle_patch.py and all other Railway updater patches.
Retains a 20-second heartbeat while an update is active.
"""
import ast
import sys
from pathlib import Path

MARKER = "# SPR_IDLE_HEARTBEAT_300_SECONDS"
OLD = "time.sleep(20 if active else 120)"
NEW = "time.sleep(20 if active else 300)"

def apply(path):
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Five-minute idle heartbeat already enabled", flush=True)
        return
    tree = ast.parse(source)
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == "updater_status_heartbeat_worker"]
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one heartbeat worker; no changes made")
    node = matches[0]
    lines = source.splitlines(keepends=True)
    block = "".join(lines[node.lineno - 1:node.end_lineno])
    if block.count(OLD) != 1:
        raise RuntimeError("Expected 120-second idle heartbeat in worker; no changes made")
    new_block = block.replace(OLD, NEW, 1)
    source = "".join(lines[:node.lineno - 1]) + new_block + "".join(lines[node.end_lineno:])
    source = MARKER + "\n" + source
    compile(source, str(path), "exec")
    path.write_text(source, encoding="utf-8")
    print("Idle Cloudflare heartbeat: 300s; active heartbeat: 20s", flush=True)

if __name__ == "__main__":
    apply(Path(sys.argv[1]))
