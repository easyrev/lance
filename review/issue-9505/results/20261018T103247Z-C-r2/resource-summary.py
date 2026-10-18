"""Read-only aggregation of preserved run records; does not execute workloads."""
import json
from collections import Counter
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
records = [json.loads(path.read_text()) | dict(run_id=path.parent.name) for path in sorted((ROOT / 'runs').glob('*/metrics.json'))]
terminal = {row['run_id']: row for row in records if row.get('status') in ('validated_success', 'resource_exhausted', 'confirmed_oom', 'source_error', 'validation_error', 'timeout/cancelled', 'infrastructure_error', 'execution_error')}
for line in (ROOT / 'run-manifest.jsonl').read_text().splitlines():
    row = json.loads(line)
    if row['run_id'] not in terminal and row.get('status') != 'planned':
        terminal[row['run_id']] = row
fields = ['merge_seconds', 'cpu_seconds', 'sampled_peak_rss_bytes', 'sampled_peak_anon_bytes']
groups = {}
for row in terminal.values():
    spec = row.get('spec', {})
    key = (spec.get('name', row.get('workload')), spec.get('source'), row.get('variant'), row.get('formal', False), 'paired' if row.get('formal') else row['run_id'])
    groups.setdefault(key, []).append(row)
out = []
for key, rows in sorted(groups.items(), key=lambda item: str(item[0])):
    successes = [row for row in rows if row.get('status') == 'validated_success']
    result = dict(workload=key[0], source=key[1], variant=key[2], formal=key[3], group=key[4], terminal_runs=len(rows),
                  states=dict(Counter(row.get('status') for row in rows)), successful_medians={}, run_ids=[row['run_id'] for row in rows])
    for field in fields:
        values = [row[field] for row in successes if row.get(field) is not None]
        if values:
            result['successful_medians'][field] = median(values)
    for field, getter in [
        ('cgroup_peak_bytes', lambda row: row.get('execution', {}).get('after', {}).get('memory.peak')),
        ('pool_observed_peak_bytes', lambda row: row.get('execute_complete', {}).get('reservation_observed_peak_bytes')),
        ('payload_take_rows', lambda row: row.get('execute_complete', {}).get('counts', {}).get('payload_take_rows')),
        ('payload_take_arrow_bytes', lambda row: row.get('execute_complete', {}).get('counts', {}).get('payload_take_arrow_bytes')),
    ]:
        values = [int(value) for row in successes if (value := getter(row)) is not None]
        if values:
            result['successful_medians'][field] = median(values)
    out.append(result)
failures = [dict(run_id=row['run_id'], variant=row.get('variant'), status=row.get('status'), spec=row.get('spec'), execution=row.get('execution'))
            for row in terminal.values() if row.get('status') != 'validated_success']
(ROOT / 'resource-summary.json').write_text(json.dumps(dict(groups=out, non_successes=failures), indent=2) + '\n')
print(json.dumps(dict(terminal_runs=len(terminal), states=dict(Counter(row['status'] for row in terminal.values()))), indent=2))
