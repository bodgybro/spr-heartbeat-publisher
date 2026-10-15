#!/usr/bin/env python3
"""Restore the original embedded roster parser as a fallback to fast discovery."""
from pathlib import Path
import sys

p=Path(sys.argv[1])
s=p.read_text(encoding="utf-8")
marker="                    if missing:\n                        raise RuntimeError(\"Roster targets unavailable after fast discovery: \"+\", \".join(missing))\n"
if s.count(marker)!=1:
    raise SystemExit("Cannot locate unique fast roster failure location")
replacement='''                    if missing:
                        # The plain HTML shortcut does not always decode TCREW
                        # web-part metadata. Use the proven embedded parser
                        # before calling this depot unavailable.
                        try:
                            discovered += _sharepoint_embedded_roster_items(page,depot_url)
                        except Exception as embedded_error:
                            print(f"    Embedded roster fallback failed: {embedded_error}",flush=True)
                        missing=[f"{role} {period}" for role in roles for period in periods if not pick_pdf(discovered,role,period)]
                        if missing:
                            try:
                                discovered += _sharepoint_rendered_items(page,depot_url)
                            except Exception as fallback_error:
                                print(f"    Rendered roster fallback failed: {fallback_error}",flush=True)
                        missing=[f"{role} {period}" for role in roles for period in periods if not pick_pdf(discovered,role,period)]
                        if missing:
                            raise RuntimeError("Roster targets unavailable after fallback discovery: "+", ".join(missing))
'''
s=s.replace(marker,replacement,1)
compile(s,str(p),"exec")
p.write_text(s,encoding="utf-8")
print("Roster embedded-page fallback restored")
