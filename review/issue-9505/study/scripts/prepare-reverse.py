"""Freeze the existing reverse fixture and its full source for one plan-only guard check."""
import hashlib
import json
from pathlib import Path
import sys
import pyarrow.ipc as ipc

ROOT = Path('/mnt/lance/hypotheses-9505-20261019')
OLD = Path('/mnt/lance/unified-9505-20261019')
sys.path.insert(0, str(OLD / 'harness'))
import fixtures
import harness

manifest = harness.verify_fixture('R_admission')
(ROOT / 'fixtures' / 'R_admission').symlink_to(OLD / 'fixtures' / 'R_admission', target_is_directory=True)
spec = fixtures.workloads()['R_admission']
directory = ROOT / 'fixtures' / 'R-admission-source-generation'
directory.mkdir()
path = ROOT / 'fixtures' / 'R-admission-source.arrow'
rows = batches = logical = 0
with path.open('wb') as output, ipc.new_file(output, fixtures.schema(spec, source=True)) as writer:
    for batch in fixtures.source_batches(spec, directory):
        writer.write_batch(batch)
        rows += batch.num_rows
        batches += 1
        logical += batch.nbytes
with path.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
assert rows == spec['source_rows']
prepared = json.loads((ROOT / 'fixtures.json').read_text())
prepared['imported']['R_admission'] = dict(original_root=str(OLD), manifest=manifest)
prepared['sources']['R_admission'] = dict(path=str(path), sha256=digest, rows=rows, batches=batches,
    arrow_logical_bytes=logical)
with Path(__file__).open('rb') as stream:
    prepared['reverse_supplement_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
(ROOT / 'fixtures.json').write_text(json.dumps(prepared, indent=2) + '\n')
