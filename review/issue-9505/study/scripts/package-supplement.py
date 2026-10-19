"""Complete reconstruction packaging without changing the frozen patch or checkout."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path('/mnt/lance/hypotheses-9505-20261019')
CHECKOUT = Path('/mnt/lance/checkouts/hypotheses-9505')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


freeze = json.loads((ROOT / 'freeze-v1.json').read_text())
name = 'rust/lance/tests/merge_insert_memory_bound.rs'
expected = freeze['full_tree_identity']['source_hashes'][name]
assert sha(CHECKOUT / name) == expected
destination = ROOT / 'snapshot' / name
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(CHECKOUT / name, destination)
addition = subprocess.run(['git', 'diff', '--no-index', '--binary', '--', '/dev/null', name],
    cwd=CHECKOUT, stdout=subprocess.PIPE, check=False)
assert addition.returncode == 1
full = ROOT / 'full-reconstruction.patch'
assert not full.exists()
full.write_bytes((ROOT / 'implementation.patch').read_bytes() + addition.stdout)
metadata = dict(inherited_untracked_file=name, sha256=expected,
    frozen_implementation_patch_sha256=sha(ROOT / 'implementation.patch'),
    full_reconstruction_patch_sha256=sha(full),
    explanation='The inherited P integration test was untracked and excluded from git diff HEAD. It was captured in the original full-tree hashes and in P-base.patch. This supplement makes the standalone patch complete; the --lib executable did not compile this integration target.')
(ROOT / 'reconstruction-supplement.json').write_text(json.dumps(metadata, indent=2) + '\n')
dependencies = {}
for suffix in ('datafusion-physical-plan-54.1.0/src/spill/in_progress_spill_file.rs',
               'datafusion-common-54.1.0/src/utils/memory.rs'):
    paths = list(Path('/mnt/lance/cache/cargo/registry/src').glob('*/' + suffix))
    assert len(paths) == 1, suffix
    target = ROOT / 'source/dependencies' / suffix
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths[0], target)
    dependencies['dependencies/' + suffix] = dict(sha256=sha(target), actual_registry_path=str(paths[0]))
(ROOT / 'source/supplemental-metadata.json').write_text(json.dumps(dependencies, indent=2) + '\n')
print(json.dumps(metadata))
