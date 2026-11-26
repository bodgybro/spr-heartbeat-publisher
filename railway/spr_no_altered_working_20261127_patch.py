#!/usr/bin/env python3
"""Apply the same explicit no-duty cover-page rule as the GitHub indexer."""
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='        if page_no in confirmed_empty_depots or entirely_empty:'
new=r'''        # SPR_NO_ALTERED_WORKING_20261127: do not relax actual duty dividers.
        import re
        page_text=str(pg.get("text",""))
        explicit_no_duty=bool(re.search(r"\bno\s+(?:(?:working\s+)?(?:shifts|duties)|altered\s+working)\b",page_text,re.I))
        has_duty=bool(re.search(r"\b(?:sign\s*on|sign\s*off|relieved\s+by|relieve\s+no|prepare\s+\d+\s+cars|shift\s+(?:no\.?\s*)?(?:[A-Z]{2,4})?\d+)\b",page_text,re.I))
        if page_no in confirmed_empty_depots or entirely_empty or (explicit_no_duty and not has_duty):'''
assert s.count(old)==1, 'Unexpected active index validator'
out=s.replace(old,new,1);compile(out,str(p),'exec')
p.write_text(out)
print("SPR_NO_ALTERED_WORKING_VALIDATOR_READY",flush=True)
