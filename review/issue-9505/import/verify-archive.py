from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parent.parent
count = 0
for line in (root / 'SHA256SUMS').read_text().splitlines():
    expected, name = line.split('  ', 1)
    path = root / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('Hash mismatch: ' + name)
    count += 1
links = json.loads((root / 'SYMLINKS.json').read_text())
actual = {str(path.relative_to(root)): str(path.readlink()) for path in root.rglob('*') if path.is_symlink()}
if actual != links:
    raise SystemExit('Symlink set or target mismatch')
for name in actual:
    path = root / name
    if not path.exists() or not path.resolve().is_relative_to(root):
        raise SystemExit('Broken or external link: ' + name)
print(json.dumps({'regular_files_verified': count, 'symlinks_verified': len(links)}))
