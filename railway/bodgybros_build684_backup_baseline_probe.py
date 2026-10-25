#!/usr/bin/env python3
"""Read-only print SHA candidates for Build684 snapshot transfer."""
from pathlib import Path
from hashlib import sha256
for version in (677,678,679,680,681,682,683,684):
 p=Path(f'/data/website-build{version}-backups/script.js')
 if p.is_file():
  data=p.read_bytes()
  print('[BUILD684 BASELINE] build='+str(version)+' sha='+sha256(data).hexdigest()+' bytes='+str(len(data)),flush=True)
 else:
  print('[BUILD684 BASELINE] build='+str(version)+' absent',flush=True)
