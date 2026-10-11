"""Independent raw-data audit. Does not import the implementation or its summarizer."""
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess

root = Path('/workspace/issue-7895-evidence')
repo = Path('/workspace/lance-7895')
snapshots = json.loads((root / 'native-snapshots.json').read_text())

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

source_hashes = {}
source_counts = {}
for label, snapshot in snapshots.items():
    assert digest(Path(snapshot['execution_native'])) == snapshot['execution_native_sha256']
    package = Path(snapshot['execution_native']).parent
    paths = subprocess.check_output(['git', '-C', str(repo), 'ls-tree', '-r', '--name-only', snapshot['code'], '--', 'python/python/lance']).decode().splitlines()
    checked = 0
    for name in paths:
        source = subprocess.check_output(['git', '-C', str(repo), 'show', f"{snapshot['code']}:{name}"])
        assert (package / Path(name).relative_to('python/python/lance')).read_bytes() == source, name
        checked += 1
    source_counts[label] = checked
    source_hashes[label] = {name: digest(package / name) for name in ('__init__.py', 'types.py', 'dataset.py')}

assert digest(root / 'final-candidate.patch') == '9694eb0eaf38d30a9ea87556163b4403ea88d7a4b54e0da6d8e8907306658ed5'
probe_hash = digest(root / 'replay_probe.so')
records = {}
intervals = []
for path in sorted((root / 'raw').glob('*.jsonl')):
    lines = path.read_text().splitlines()
    assert len(lines) == 1, path
    d = json.loads(lines[0])
    assert path.with_suffix('.stderr').read_text() == '', path
    fixture = 'benchmark-fixture-small' if d['fixture']['rows'] == 8192 else 'benchmark-fixture'
    key = fixture, d['label'], d['kind'], d['conflict'], d['trial']
    assert key not in records
    records[key] = d
    assert d == json.loads((root / fixture / f"{d['label']}-{d['kind']}-{'conflict' if d['conflict'] else 'clean'}-{d['trial']}" / 'result.json').read_text())
    assert d['correct'] and d['error'] is None
    assert d['extension_sha256'] == snapshots[d['label']]['execution_native_sha256']
    assert d['source_sha256'] == source_hashes[d['label']]
    assert d['probe_sha256'] == probe_hash
    assert d['pyarrow'] == '25.0.1'
    assert set(d['thread_limits'].values()) == {'4'}
    assert d['arrow_cpu_count'] == d['arrow_io_thread_count'] == 4
    assert d['commit_versions'] == ([2, 3] if d['conflict'] else [2])
    assert d['concurrent_versions'] == ([2] if d['conflict'] else [])
    assert d['final_version'] == (3 if d['conflict'] else 2)
    assert d['final_rows'] == d['fixture']['rows']
    assert d['payload_sha256'] == d['fixture']['payload_sha256']
    assert d['stats'] == {'num_inserted_rows': d['final_rows'] - 1, 'num_updated_rows': 1, 'num_deleted_rows': 0}
    expected_dirs = int(d['label'] == 'baseline' or d['kind'] == 'scanner')
    assert d['replay_directory_count'] == expected_dirs
    expected_spill = expected_dirs if fixture == 'benchmark-fixture' else 0
    assert d['spill_file_count'] == expected_spill
    assert bool(d['spill_file_unlink_bytes']) == bool(expected_spill)
    trial_id = f"{fixture}-{d['label']}-{d['kind']}-{'conflict' if d['conflict'] else 'clean'}-{d['trial']}"
    events = [line.split('\t') for line in (root / 'probes' / trial_id / 'events.tsv').read_text().splitlines()]
    assert sum(e[0] == 'mkdir' and Path(e[1]).name.startswith('.tmp') for e in events) == expected_dirs
    assert sum(int(e[2]) for e in events if e[0] == 'unlink' and e[1].endswith('spill.arrows')) == d['spill_file_unlink_bytes']
    assert d['first_commit_elapsed_s'] == d['commit_events'][0]['entered_s']
    assert 0 < d['first_commit_elapsed_s'] < d['elapsed_s']
    assert 0 <= d['first_commit_cpu_s'] <= d['cpu_s'] + 1e-9
    assert math.isclose(d['cpu_s'], d['user_s'] + d['system_s'], abs_tol=1e-9)
    last = 0
    for e in d['commit_events']:
        assert last < e['entered_s'] <= e['released_s'] < d['elapsed_s']
        last = e['released_s']
    if d['conflict']:
        e = d['commit_events'][0]
        assert e['entered_s'] <= e['update_started_s'] < e['update_finished_s'] <= e['released_s']
    intervals.append((d['wall_start_ns'], d['wall_end_ns'], trial_id))

assert len(records) == 120
intervals.sort()
assert all(a[1] < b[0] for a, b in zip(intervals, intervals[1:])), 'overlapping timed samples'
summary_metrics = ('elapsed_s', 'first_commit_elapsed_s', 'first_commit_cpu_s', 'cpu_s', 'concurrent_update_elapsed_s', 'max_rss_kib', 'replay_directory_count', 'spill_file_count', 'spill_file_unlink_bytes')
table = []
for fixture in ('benchmark-fixture-small', 'benchmark-fixture'):
    summaries = json.loads((root / f'{fixture}-summary.json').read_text())
    assert len(summaries) == 12
    for s in summaries:
        rows = [records[(fixture, s['label'], s['kind'], s['conflict'], str(i))] for i in range(1, 6)]
        assert s['count'] == 5
        for metric in summary_metrics:
            values = [d[metric] for d in rows]
            assert s[metric]['values'] == values, (fixture, s['label'], metric)
            assert s[metric]['median'] == statistics.median(values)
            assert s[metric]['min'] == min(values) and s[metric]['max'] == max(values)
    for kind in ('lance', 'arrow', 'scanner'):
        for conflict in (False, True):
            a = [records[(fixture, 'baseline', kind, conflict, str(i))] for i in range(1, 6)]
            b = [records[(fixture, 'candidate', kind, conflict, str(i))] for i in range(1, 6)]
            table.append({'fixture': fixture, 'kind': kind, 'conflict': conflict,
                          'medians': {k: [statistics.median(r[k] for r in rows) for rows in (a, b)] for k in summary_metrics},
                          'paired_elapsed_ratios': [y['elapsed_s'] / x['elapsed_s'] for x, y in zip(a, b)]})
            for i, (x, y) in enumerate(zip(a, b), 1):
                assert (x['wall_start_ns'] < y['wall_start_ns']) == bool(i % 2)

plans = []
for fixture in ('benchmark-fixture-small', 'benchmark-fixture'):
    for kind in ('lance', 'arrow', 'scanner'):
        dirs = [root / 'plans' / fixture / label / kind for label in ('baseline', 'candidate')]
        assert (dirs[0] / 'topology.txt').read_bytes() == (dirs[1] / 'topology.txt').read_bytes()
        metrics = []
        for label, folder in zip(('baseline', 'candidate'), dirs):
            metadata = json.loads((folder / 'metadata.json').read_text())
            assert metadata['extension_sha256'] == snapshots[label]['execution_native_sha256']
            assert metadata['target_unchanged'] and metadata['commit_versions'] == []
            assert metadata['before_version'] == metadata['after_version'] == 1
            plan = (folder / 'actual-plan.txt').read_text()
            metrics.append(re.findall(r'\b(?:output_rows|input_rows|output_batches|input_batches)=[^,\]]+', plan))
        assert metrics[0] == metrics[1], (fixture, kind, metrics)
        plans.append({'fixture': fixture, 'kind': kind, 'topology_and_row_batch_metrics_equal': True})

controls = []
for path in sorted((root / 'controls/final').glob('*.jsonl')):
    d = json.loads(path.read_text())
    label = d['label'].removeprefix('controls-final-')
    assert path.with_suffix('.stderr').read_text() == ''
    assert d['extension_sha256'] == snapshots[label]['execution_native_sha256']
    assert d['source_sha256'] == source_hashes[label]
    assert d['correct']
    assert d['fixture']['arrow_bytes'] == 256
    replay = d['kind'] != 'table' and d['retries'] != 0 and (label == 'baseline' or d['kind'] in ('oneshot', 'scanner'))
    assert d['replay_directory_count'] == int(replay)
    assert d['spill_file_count'] == d['spill_file_unlink_bytes'] == 0
    assert bool(d['error']) == (d['retries'] == 0)
    assert d['commit_versions'] == ([2, 3] if d['conflict'] and d['retries'] else [2])
    controls.append(path.name)
assert len(controls) == 14

followup = {}
for path in sorted((root / 'no-probe-followup').glob('*.jsonl')):
    d = json.loads(path.read_text())
    assert path.with_suffix('.stderr').read_text() == ''
    label = d['label'].removeprefix('no-probe-')
    assert d['correct'] and d['error'] is None and d['probe_sha256'] is None
    assert d['extension_sha256'] == snapshots[label]['execution_native_sha256']
    assert d['source_sha256'] == source_hashes[label]
    assert d['kind'] == 'lance' and not d['conflict'] and d['commit_versions'] == [2]
    assert d['final_rows'] == 8192 and d['payload_sha256'] == d['fixture']['payload_sha256']
    assert set(d['thread_limits'].values()) == {'4'}
    followup[(label, int(d['trial']))] = d
assert len(followup) == 20
ratios = []
for i in range(1, 11):
    a, b = (followup[(label, i)] for label in ('baseline', 'candidate'))
    assert (a['wall_start_ns'] < b['wall_start_ns']) == bool(i % 2)
    ratios.append(b['elapsed_s'] / a['elapsed_s'])
followup_metrics = {k: {label: {'median': statistics.median(followup[(label, i)][k] for i in range(1, 11)), 'min': min(followup[(label, i)][k] for i in range(1, 11)), 'max': max(followup[(label, i)][k] for i in range(1, 11))} for label in ('baseline', 'candidate')} for k in ('elapsed_s', 'cpu_s', 'first_commit_elapsed_s', 'first_commit_cpu_s')}

out = {'passed': True, 'primary_samples': len(records), 'controls': len(controls), 'followup_samples': len(followup), 'native_hashes_recomputed': {k: v['execution_native_sha256'] for k, v in snapshots.items()}, 'git_source_files_verified': source_counts, 'primary_comparisons': table, 'plans': plans, 'followup': followup_metrics, 'followup_paired_elapsed_ratios': ratios, 'followup_slower_candidate_pairs': sum(x > 1 for x in ratios)}
(root / 'independent-performance-check.json').write_text(json.dumps(out, indent=2) + '\n')
print(json.dumps({'passed': True, 'primary_samples': len(records), 'controls': len(controls), 'followup_samples': len(followup), 'git_source_files_verified': source_counts, 'followup': followup_metrics, 'followup_slower_candidate_pairs': sum(x > 1 for x in ratios)}, indent=2))
