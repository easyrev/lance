from pathlib import Path
import hashlib
import json

root=Path(__file__).resolve().parent.parent
count=0
for line in (root/'SHA256SUMS').read_text().splitlines():
    expected,name=line.split('  ',1)
    path=root/name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise SystemExit('Hash mismatch: '+name)
    count+=1
print(json.dumps({'regular_files_verified':count}))
