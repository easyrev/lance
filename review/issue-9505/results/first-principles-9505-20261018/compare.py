"""Run sequential exploratory comparisons in fresh worker cgroups."""

import json
import random
import sys
from pathlib import Path

import bench

stage = sys.argv[1]
variants = [('Ccore', 'rewrite_rows'), ('Clate', 'rewrite_rows'), ('Ccore', 'rewrite_columns')]
if stage == 'smoke':
    cells = [(name, variant, mode, 0, False) for name in ('Wn', 'Ws', 'F16') for variant, mode in variants]
elif stage == 'pairs':
    cells = []
    rng = random.Random(9518)
    for block in range(1, 4):
        for name in ('Wn', 'Ws', 'F16'):
            order = variants.copy()
            rng.shuffle(order)
            cells.extend((name, variant, mode, block, True) for variant, mode in order)
else:
    raise ValueError(stage)
for name, variant, mode, block, formal in cells:
    spec = bench.workload(name) | {'write_mode': mode}
    run_id = f'{stage}-{name}-{variant}-{mode}-b{block}'
    status = bench.run(variant, spec, run_id, block=block, formal=formal, timeout=120)
    if status != 'validated_success':
        raise RuntimeError(f'{run_id}: {status}')
rows = []
for path in sorted((bench.ROOT / 'runs').glob('*/metrics.json')):
    m = json.loads(path.read_text())
    rows.append({key: m.get(key) for key in ('run_id', 'status', 'formal', 'block', 'merge_seconds', 'cpu_seconds', 'sampled_peak_rss_bytes', 'new_data_file_bytes', 'new_data_file_count')})
(bench.ROOT / 'summary.json').write_text(json.dumps(rows, indent=2))
print(json.dumps(rows), flush=True)
