#!/usr/bin/env python3
"""Conservative Railway updater traffic reduction after the Build 700 patches.

- Active heartbeat: 60 seconds (previously 20), idle stays 300 seconds.
- Back off a blocked roster relay after a failed HTTP response, rather than
  retrying every 5 seconds. Leaves successful relay and real update paths alone.
- Never changes schedule, credentials, cached PDFs, roster lists or SPR logic.
"""
import ast
import os
import re
import sys
import tempfile
from pathlib import Path

MARKER = "# SPR_CF_TRAFFIC_OPT_20261031"
OLD_HEARTBEAT = "time.sleep(20 if active else 300)"
NEW_HEARTBEAT = "time.sleep(60 if active else 300)"
RELAY_MARKER = "# SPR_ROSTER_RELAY_HTTP_BACKOFF_180"

def apply(path):
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("[CLOUDFLARE OPTIMISATION] Already installed", flush=True)
        return
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == "updater_status_heartbeat_worker"]
    if len(functions) != 1:
        raise RuntimeError("Cannot safely identify heartbeat worker; no changes made")
    n = functions[0]
    lines = source.splitlines(keepends=True)
    heartbeat = "".join(lines[n.lineno-1:n.end_lineno])
    if heartbeat.count(OLD_HEARTBEAT) != 1:
        raise RuntimeError("Expected active 20s/idle 300s heartbeat, no changes made")
    heartbeat = heartbeat.replace(OLD_HEARTBEAT, NEW_HEARTBEAT, 1)
    changed = "".join(lines[:n.lineno-1]) + heartbeat + "".join(lines[n.end_lineno:])
    relay_patched = False
    relay_tree = ast.parse(changed)
    matches = []
    for node in ast.walk(relay_tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "print":
            continue
        segment = ast.get_source_segment(changed, node) or ""
        if "Roster relay HTTP" in segment:
            matches.append(node)
    if len(matches) == 1:
        node = matches[0]
        relay_lines = changed.splitlines(keepends=True)
        statement = relay_lines[node.lineno-1]
        indent = re.match(r"^(\s*)", statement).group(1)
        # Insert only when the failure print is a complete standalone statement.
        if statement.lstrip().startswith("print(") and relay_lines[node.end_lineno-1].rstrip().endswith(")"):
            relay_lines.insert(node.end_lineno, indent + "time.sleep(180)  " + RELAY_MARKER + "\n")
            changed = "".join(relay_lines)
            relay_patched = True
    elif matches:
        print(f"[ROSTER RELAY BACKOFF] Found {len(matches)} HTTP log sites; skipped ambiguous edit", flush=True)
    else:
        print("[ROSTER RELAY BACKOFF] HTTP 409 log is not in updater module; skipped", flush=True)
    changed = MARKER + "\n" + changed
    compile(changed, str(path), "exec")
    with tempfile.NamedTemporaryFile("w", dir=str(path.parent), prefix=".cf-opt-", delete=False, encoding="utf-8") as handle:
        handle.write(changed)
        temp_name = handle.name
    try:
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    print("[CLOUDFLARE OPTIMISATION] Active heartbeat 60s, idle 300s", flush=True)
    print("[ROSTER RELAY BACKOFF] " + ("180s delay after HTTP failure" if relay_patched else "No relay source changed"), flush=True)

if __name__ == "__main__":
    apply(Path(sys.argv[1]))
