"""Prepare isolated exploratory comparisons from the frozen C-r2 harness."""

import hashlib
import json
import os
import shutil
from pathlib import Path

original = Path('/mnt/lance/validation-9505/results/20261018T103247Z-C-r2')
root = Path('/mnt/lance/first-principles-9505-20261018')
root.mkdir(exist_ok=False)
frozen = json.loads((original / 'freeze.json').read_text())
for name, expected in frozen['source_hashes'].items():
    path = Path('/mnt/lance/checkouts/C') / name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, str(path)
for variant in ('C', 'U'):
    entry = frozen['identities'][variant]
    assert hashlib.sha256(Path(entry['extension']).read_bytes()).hexdigest() == entry['extension_sha256']

source = (original / 'bench.py').read_text()
assert source.count('.write_mode("rewrite_rows")') == 1
source = source.replace('.write_mode("rewrite_rows")', '.write_mode(spec.get("write_mode", "rewrite_rows"))')
anchor = '    cpu_start = resource.getrusage(resource.RUSAGE_SELF)\n'
assert source.count(anchor) == 1
source = source.replace(anchor, '    initial_files = {str(path) for path in uri.rglob("*.lance")}\n' + anchor)
anchor = '    result["stage"] = "execute_finished"\n'
assert source.count(anchor) == 1
source = source.replace(anchor, '    new_files = [path for path in uri.rglob("*.lance") if str(path) not in initial_files]\n    result["new_data_file_bytes"] = sum(path.stat().st_size for path in new_files)\n    result["new_data_file_count"] = len(new_files)\n' + anchor)
(root / 'bench.py').write_text(source)
(root / 'parent-freeze.json').write_text(json.dumps(frozen, indent=2))
(root / 'provenance.json').write_text(json.dumps({
    'purpose': 'Exploratory write-strategy and omitted-column comparisons; not historical C-r2 runs',
    'original': str(original),
    'product_source_changes': False,
    'harness_sha256': hashlib.sha256(source.encode()).hexdigest(),
    'new_data_file_bytes': 'Final sizes of newly created .lance files; excludes manifests, deletions, temporary writes, reads and compaction',
    'copy': 'Immutable data files hard-linked; metadata copied independently',
}, indent=2))

def copy_file(src, dst):
    if Path(src).suffix == '.lance':
        os.link(src, dst)
        return dst
    return shutil.copy2(src, dst)

for name in ('Wn', 'Ws', 'F16'):
    old = original / 'fixtures' / name
    new = root / 'fixtures' / name
    shutil.copytree(old, new, copy_function=copy_file)
    meta = json.loads((new / 'fixture.json').read_text())
    meta['files'] = [str(new / 'data' / Path(path).name) for path in meta['files']]
    assert all(Path(path).is_file() for path in meta['files'])
    (new / 'fixture.json').write_text(json.dumps(meta, indent=2))
print(root, flush=True)
