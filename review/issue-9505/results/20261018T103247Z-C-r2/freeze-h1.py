"""Create a provenance checkpoint for the reviewed post-exit cleanup correction."""
import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECKOUT = Path('/mnt/lance/checkouts/C')

def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()

frozen = json.loads((ROOT / 'harness-r0/freeze.json').read_text())
assert json.loads((ROOT / 'freeze.json').read_text()) == frozen
review = ROOT / 'diagnostics/review-h1.md'
assert review.exists() and 'CLEARANCE' in review.read_text()
for name, expected in frozen['source_hashes'].items():
    assert digest(CHECKOUT / name) == expected, name
for variant, identity in frozen['identities'].items():
    assert digest(identity['extension']) == identity['extension_sha256'], variant
assert digest('/mnt/lance/targets/C/release-with-debug/deps/lance-31a368c8670aef12') == frozen['test_binary_sha256']
for name, expected in frozen['input_hashes'].items():
    assert digest(Path('/mnt/lance/validation-9505') / name) == expected, name
assert digest('/mnt/lance/RESTORED-ENVIRONMENT.md') == frozen['handoff_sha256']
assert digest(ROOT / 'C.patch') == frozen['patch_sha256']
for name, expected in frozen['harness_hashes'].items():
    assert digest(ROOT / 'harness-r0' / name) == expected, name
    if name != 'bench.py':
        assert digest(ROOT / name) == expected, name
frozen.update(harness_revision='h1', parent_freeze='harness-r0/freeze.json',
              parent_freeze_sha256=digest(ROOT / 'harness-r0/freeze.json'),
              original_frozen_at=frozen['frozen_at'], frozen_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              harness_reviewer_sha256=digest(review), harness_patch_sha256=digest(ROOT / 'diagnostics/harness-h1.patch'))
frozen['harness_hashes'] = {name: digest(ROOT / name) for name in frozen['harness_hashes']}
(ROOT / 'freeze.json').write_text(json.dumps(frozen, indent=2) + '\n')
manifest = json.loads((ROOT / 'manifest.json').read_text())
manifest.update(freeze=frozen, harness_revision='h1', status='source C-r2 unchanged; harness h1 reviewed and frozen; remaining finite cells authorized')
(ROOT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(dict(source_revision=frozen['revision'], harness_revision='h1', bench_sha256=frozen['harness_hashes']['bench.py'], parent_freeze_sha256=frozen['parent_freeze_sha256'], new_freeze_sha256=digest(ROOT / 'freeze.json'))))
