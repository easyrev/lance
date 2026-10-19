"""Verify saved results and frozen identities without re-executing workloads."""
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path('/mnt/lance/hypotheses-9505-20261019')
OLD = Path('/mnt/lance/unified-9505-20261019')
CHECKOUT = Path('/mnt/lance/checkouts/hypotheses-9505')
sys.path.insert(0, str(OLD / 'harness'))
import harness as h


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    errors = []
    counters = {}
    def check(condition, message, category):
        counters[category] = counters.get(category, 0) + 1
        if not condition:
            errors.append(message)
    def hashed(path, expected, category):
        path = Path(path)
        check(path.is_file() and sha(path) == expected, str(path), category)

    h.no_builds()
    freeze = read(ROOT / 'freeze-v1.json')
    frozen_sha = sha(ROOT / 'freeze-v1.json')
    hashed(freeze['binary']['path'], freeze['binary']['sha256'], 'binary')
    hashed(freeze['binary']['compiler_artifact']['executable'], freeze['binary']['sha256'], 'binary')
    for name, expected in freeze['full_tree_identity']['source_hashes'].items():
        hashed(CHECKOUT / name, expected, 'workspace_source')
    check(h.tree_identity(CHECKOUT) == freeze['full_tree_identity'], 'full live tree identity', 'workspace_tree')
    for name, expected in freeze['source_hashes'].items():
        hashed(ROOT / 'snapshot' / name, expected, 'snapshot')
    for name, expected in freeze['harness_hashes'].items():
        hashed(ROOT / name, expected, 'harness')
    hashed(ROOT / 'implementation.patch', freeze['implementation_patch_sha256'], 'patch')
    hashed(ROOT / 'fixtures.json', freeze['fixture_identity_sha256'], 'fixture_metadata')
    hashed(OLD / 'harness/harness.py', freeze['previous_harness_sha256'], 'previous_harness')
    pair_freeze = read(ROOT / 'paired-freeze.json')
    check(pair_freeze['freeze_v1_sha256'] == frozen_sha, 'paired freeze identity', 'paired_freeze')
    hashed(ROOT / 'config.json', pair_freeze['global_config_sha256'], 'paired_freeze')
    hashed(ROOT / 'paired-plan.json', pair_freeze['paired_plan_sha256'], 'paired_freeze')
    check(pair_freeze['source_and_harness_reverified'], 'pre-pair verification', 'paired_freeze')
    for name, expected in read(ROOT / 'source/metadata.json')['files'].items():
        hashed(ROOT / 'source' / name, expected, 'source_export')
        if name.startswith('dependencies/'):
            suffix = name.removeprefix('dependencies/')
            matches = list(Path('/mnt/lance/cache/cargo/registry/src').glob('*/' + suffix))
            check(len(matches) == 1, 'registry match: ' + suffix, 'dependency_lookup')
            if len(matches) == 1:
                hashed(matches[0], expected, 'actual_dependency_source')
    fixtures = read(ROOT / 'fixtures.json')
    for name, item in fixtures['imported'].items():
        for relative, expected in item['manifest']['files'].items():
            hashed(ROOT / 'fixtures' / name / relative, expected, 'imported_fixture')
    for name, item in fixtures['generated'].items():
        paths = {str(path.relative_to(item['path'])) for path in Path(item['path']).rglob('*') if path.is_file()}
        check(paths == set(item['files']), name + ': generated file set', 'generated_fixture')
        for relative, expected in item['files'].items():
            hashed(Path(item['path']) / relative, expected, 'generated_fixture')
    for name, item in fixtures['sources'].items():
        hashed(item['path'], item['sha256'], 'source_ipc')
    check(h.identity() == fixtures['validator_identity'], 'validator live identity', 'validator')
    for line in (OLD / 'SHA256SUMS').read_text().splitlines():
        expected, relative = line.split('  ', 1)
        hashed(OLD / relative, expected, 'previous_archive')

    plans = [read(ROOT / name) for name in ('diagnostic-plan.json', 'paired-plan.json')]
    expected = {cell['name']: cell['spec'] for plan in plans for cell in plan['cells']}
    actual = {p.name for p in (ROOT / 'runs').iterdir() if p.is_dir()}
    check(set(expected) == actual, 'run names differ from registered plans', 'run_set')
    statuses = {}
    task_statuses = {}
    for name, spec in expected.items():
        directory = ROOT / 'runs' / name
        record = read(directory / 'result.json')
        metrics = read(directory / 'metrics.json')
        validation = read(directory / 'validate.json')
        check(read(directory / 'spec.json') == spec == record['spec'], name + ': spec', 'run')
        hashed(directory / 'spec.json', record['spec_sha256'], 'run')
        check(record['freeze_sha256'] == frozen_sha, name + ': freeze', 'run')
        check(record['metrics'] == metrics and record['validation'] == validation, name + ': embedded records', 'run')
        resource = record['resource']
        check(resource['exit_code'] == 0 and not resource['timeout'] and not resource['confirmed_oom'], name + ': process', 'run')
        check(resource['command'][0] == freeze['binary']['path'], name + ': executable path', 'run')
        check(resource['before']['memory.max'] == str(8 << 30) and resource['before']['memory.swap.max'] == '0', name + ': cgroup', 'run')
        check(validation['validated'] and validation['validator_identity'] == fixtures['validator_identity'], name + ': oracle', 'run')
        status = metrics['status']
        statuses[status] = statuses.get(status, 0) + 1
        key = spec['task'] + ':' + status
        task_statuses[key] = task_statuses.get(key, 0) + 1
        if status != 'success':
            check(spec['task'] == 'merge' and validation['unchanged'], name + ': unchanged oracle', 'run')
        if name.startswith('pairs-'):
            check(status == 'success', name + ': paired failure', 'run')
        for relative, item in validation['validated_output_files'].items():
            hashed(directory / relative, item['sha256'], 'stage_output')
    comparisons = []
    for item in plans[1]['comparisons']:
        values = []
        for block in range(1, 4):
            left = read(ROOT / 'runs' / f"{item['group']}-b{block}-{item['numerator']}" / 'result.json')
            right = read(ROOT / 'runs' / f"{item['group']}-b{block}-{item['denominator']}" / 'result.json')
            check(left['metrics']['status'] == right['metrics']['status'] == 'success', 'paired status', 'pairs')
            values.append(left['metrics']['merge_seconds'] / right['metrics']['merge_seconds'])
        comparisons.append(item | dict(ratios=values, median_ratio=sorted(values)[1]))
    for name in ('build-probe', 'diagnostics', 'pairs', 'unit-tests'):
        check((ROOT / 'logs' / (name + '-exit-code')).read_text().strip() == '0', name + ' exit', 'execution_logs')
    result = dict(status='passed' if not errors else 'failed', errors=errors, counters=counters,
        statuses=statuses, task_statuses=task_statuses, run_count=len(expected),
        comparisons=comparisons, source_freeze_sha256=frozen_sha,
        binary_sha256=freeze['binary']['sha256'], verified_at=time.time(),
        scope='Hash audit of saved records, output files, current frozen sources, loaded-executable path/hash, dependency sources and fixtures; does not rerun field oracles.',
        limitations=['Not a workspace CI or upstream acceptance claim.', 'Sampled process memory is not a hard bound.'])
    (ROOT / 'audit-final.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(errors))


if __name__ == '__main__':
    main()
