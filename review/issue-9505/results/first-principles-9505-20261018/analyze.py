"""Summarize exploratory pairs without mixing them with diagnostic runs."""

import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

root = Path(__file__).resolve().parent
frozen = json.loads((root / 'parent-freeze.json').read_text())
for name, expected in frozen['source_hashes'].items():
    assert hashlib.sha256((Path('/mnt/lance/checkouts/C') / name).read_bytes()).hexdigest() == expected
for variant in ('C', 'U'):
    item = frozen['identities'][variant]
    assert hashlib.sha256(Path(item['extension']).read_bytes()).hexdigest() == item['extension_sha256']
records = [json.loads(path.read_text()) for path in sorted((root / 'runs').glob('*/metrics.json'))]
assert len(records) == 36, len(records)
assert all(row['status'] == 'validated_success' for row in records)
groups = defaultdict(list)
for row in records:
    if row['formal']:
        groups[(row['spec']['name'], row['variant'], row['spec']['write_mode'])].append(row)
summary = []
for key, group in sorted(groups.items()):
    assert len(group) == 3
    times = [row['merge_seconds'] for row in group]
    summary.append({
        'workload': key[0], 'variant': key[1], 'write_mode': key[2], 'n': 3,
        'median_seconds': statistics.median(times),
        'range_seconds': [min(times), max(times)],
        'median_new_data_file_bytes': statistics.median(row['new_data_file_bytes'] for row in group),
        'median_new_data_files': statistics.median(row['new_data_file_count'] for row in group),
        'median_sampled_peak_rss_bytes': statistics.median(row['sampled_peak_rss_bytes'] for row in group),
        'median_cpu_seconds': statistics.median(row['cpu_seconds'] for row in group),
    })
ratios = []
for name in ('Wn', 'Ws', 'F16'):
    a = {row['block']: row for row in groups[(name, 'Ccore', 'rewrite_rows')]}
    b = {row['block']: row for row in groups[(name, 'Clate', 'rewrite_rows')]}
    c = {row['block']: row for row in groups[(name, 'Ccore', 'rewrite_columns')]}
    for label, top, bottom in [('late/early', b, a), ('columns/early', c, a), ('columns/late', c, b)]:
        values = [top[i]['merge_seconds'] / bottom[i]['merge_seconds'] for i in (1, 2, 3)]
        ratios.append({'workload': name, 'ratio': label, 'median': statistics.median(values), 'values': values})
result = {
    'scope': 'Exploratory comparison, 9 diagnostic runs plus 27 randomized paired runs, n=3 per cell; not the historical C-r2 formal study',
    'verified': 'All 36 runs independently read back every row and field using frozen U; C/U source and extension hashes unchanged',
    'upstream_main_checked': '0a0d327082988018a25f56147d3b6d02f6c79ecc',
    'benchmark_base': 'dc53d5d174af62c49ddd98d1024a64488c1e4404 plus frozen C-r2 patch',
    'conditions': 'Local NVMe, hot initial files, fresh worker cgroup, 1 GiB DF pool, 8 GiB cgroup, lazy source, index disabled, retry disabled',
    'timer': 'Merge API includes lazy source production, planning, reads, writes and commit; restore, prewarming and independent validation excluded',
    'storage_size_scope': 'Final size of newly created .lance files only; not complete read/write traffic, temporary spill, metadata, cloud requests or future maintenance',
    'groups': summary, 'paired_ratios': ratios,
}
(root / 'analysis.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
