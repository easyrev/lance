"""Apply the complete patch to an exported clean baseline and verify source bytes."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path('/mnt/lance/hypotheses-9505-20261019')
CHECKOUT = Path('/mnt/lance/checkouts/hypotheses-9505')
freeze = json.loads((ROOT / 'freeze-v1.json').read_text())
destination = ROOT / 'reconstruction-check-tmp'
destination.mkdir(exist_ok=False)
export = subprocess.Popen(['git', '-C', str(CHECKOUT), 'archive', freeze['base_commit']], stdout=subprocess.PIPE)
subprocess.run(['tar', '-x', '-C', str(destination)], stdin=export.stdout, check=True)
export.stdout.close()
assert export.wait() == 0
subprocess.run(['git', '-C', str(destination), 'init', '--quiet'], check=True)
subprocess.run(['git', '-C', str(destination), 'apply', '--check', str(ROOT / 'full-reconstruction.patch')], check=True)
subprocess.run(['git', '-C', str(destination), 'apply', str(ROOT / 'full-reconstruction.patch')], check=True)
errors = []
for name, expected in freeze['full_tree_identity']['source_hashes'].items():
    with (destination / name).open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != expected:
        errors.append(name)
result = dict(status='passed' if not errors else 'failed', errors=errors,
    verified_source_files=len(freeze['full_tree_identity']['source_hashes']),
    method='git archive U, apply full reconstruction patch, hash every originally frozen workspace source/lock file; no build')
(ROOT / 'reconstruction-check.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
raise SystemExit(bool(errors))
