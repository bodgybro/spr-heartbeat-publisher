#!/usr/bin/env python3
"""Compatibility shim for 609 online updater before pinned fast_roster_patch.py.

The earlier command/heartbeat patches leave the original roster upload call,
while the fast-roster patch expects the retry wrapper name to be present.
The wrapper itself is inserted by the fast-roster patch.
"""
from pathlib import Path
import sys
p=Path(sys.argv[1])
s=p.read_text(encoding="utf-8")
old="                            upload_cached_roster_pdf(pdf_url,pdf_name,data,cache_path)\n"
new="                            _store_roster_fast(pdf_url,pdf_name,data,cache_path)\n"
if old in s:
    if s.count(old)!=1:
        raise SystemExit("Unexpected number of roster upload calls")
    s=s.replace(old,new,1)
    p.write_text(s,encoding="utf-8")
    print("Fast roster compatibility shim applied")
elif new in s:
    print("Fast roster compatibility shim already applied")
else:
    raise SystemExit("Fast roster compatibility shim: expected upload call not found")
