#!/usr/bin/env python3
"""Avoid reusing a closed Chromium context between manual ROC report dates.

Apply AFTER ROC_MANUAL_COMMAND_20261114_V1 and the staged three-source catch-up.
Each historical CSV report uses a fresh authenticated browser context. The
existing exclusive SHAREPOINT_BROWSE_LOCK, immutable dual-site CSV validation,
cancel protection, and success timestamps remain unchanged.
"""
import ast
import sys
from pathlib import Path

MARKER = "# ROC_MANUAL_FRESH_CONTEXT_PER_DATE_20261123_V1"

def apply(path):
    src = path.read_text(encoding="utf-8")
    if MARKER in src:
        print("ROC_FRESH_CONTEXT_ALREADY_APPLIED", flush=True)
        return
    for required in (
        "# ROC_MANUAL_COMMAND_20261114_V1",
        "def _roc_manual_check():",
        "with SHAREPOINT_BROWSE_LOCK:",
        "def _spr_recovery_roc_success():",
        "    _spr_recovery_roc_success()",
    ):
        if src.count(required) != 1:
            raise RuntimeError("Missing unique deployed ROC hook: " + required)
    tree = ast.parse(src)
    matches = [n for n in tree.body if isinstance(n, ast.FunctionDef)
               and n.name == "_roc_manual_check"]
    if len(matches) != 1:
        raise RuntimeError("Manual ROC function not unique")
    node = matches[0]
    lines = src.splitlines(keepends=True)
    body = "".join(lines[node.lineno - 1:node.end_lineno])
    start = "    with SHAREPOINT_BROWSE_LOCK:\n"
    end = "    dates=\", \".join(d.isoformat() for d in targets)\n"
    if body.count(start) != 1 or body.count(end) != 1:
        raise RuntimeError("Manual ROC browser lifecycle changed")
    a = body.index(start)
    b = body.index(end, a)
    existing = body[a:b]
    expected = (
        "                browser=_launch_sharepoint_context(",
        "                    for report_date in targets:",
        "                        if not roc_worker.process(browser, globals(), target_date=report_date):",
        "                    browser.close()",
        "            _wait_for_sharepoint_profile_release()",
    )
    if any(existing.count(e) != 1 for e in expected):
        raise RuntimeError("Unexpected existing ROC browser lifecycle")
    replacement = '''    with SHAREPOINT_BROWSE_LOCK:
        # Persistent Chromium may close its context after the previous
        # report page closes. Never navigate another date on that context.
        for report_date in targets:
            _check_online_cancel()
            _set_online_progress("ROC: checking "+report_date.isoformat()+" in SharePoint")
            for attempt in range(2):
                try:
                    with sync_playwright() as p:
                        browser=_launch_sharepoint_context(
                            p,cfg,
                            headless=str(os.environ.get("SPR_HEADLESS","0")).strip().lower() in
                                ("1","true","yes","on"),
                            ignore_https_errors=True,accept_downloads=True,
                            args=["--window-size=900,650","--window-position=20,20"],
                            no_viewport=True)
                        try:
                            if not roc_worker.process(browser, globals(), target_date=report_date):
                                raise RuntimeError("ROC "+report_date.isoformat()+" verification failed")
                            _check_online_cancel()
                        finally:
                            # A closed context is expected after a browser crash;
                            # do not let cleanup hide the original exception.
                            try:
                                browser.close()
                            except Exception:
                                pass
                    break
                except Exception as exc:
                    problem=str(exc).lower()
                    context_closed=("target page" in problem or
                                    "browser has been closed" in problem or
                                    "context or browser has been closed" in problem)
                    if not context_closed or attempt:
                        raise
                    print("[ROC DOMO] Browser context closed while processing "+
                          report_date.isoformat()+"; reopening once",flush=True)
                    _check_online_cancel()
                finally:
                    _wait_for_sharepoint_profile_release()
'''
    changed = body[:a] + replacement + body[b:]
    if changed.count("roc_worker.process(") != 1:
        raise RuntimeError("Unexpected ROC date-processing count")
    if changed.count("_record_online_success(\"roc\")") != 1:
        raise RuntimeError("Verified ROC completion hook changed")
    if changed.count("_spr_recovery_roc_success()") != 1:
        raise RuntimeError("Automatic catch-up ROC success marker changed")
    updated = (MARKER + "\n" +
               "".join(lines[:node.lineno - 1]) +
               changed.rstrip() + "\n" +
               "".join(lines[node.end_lineno:]))
    ast.parse(updated)
    compile(updated, str(path), "exec")
    path.write_text(updated, encoding="utf-8")
    print("ROC_MANUAL_FRESH_CONTEXT_PATCH_PASS fresh_context_per_date=yes "
          "one_retry_on_target_closed=yes immutable_reports=yes "
          "manual_cancel_and_lock_preserved=yes catchup_marker_preserved=yes",
          flush=True)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch.py spr_online_updater.py")
    apply(Path(sys.argv[1]))
