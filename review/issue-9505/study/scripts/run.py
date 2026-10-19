"""Run frozen, falsifiable probes using the existing cgroup sampler and oracle code."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

ROOT = Path('/mnt/lance/hypotheses-9505-20261019')
OLD = Path('/mnt/lance/unified-9505-20261019')
CHECKOUT = Path('/mnt/lance/checkouts/hypotheses-9505')
U = Path('/mnt/lance/checkouts/U_main/python')
sys.path.insert(0, str(OLD / 'harness'))
import harness as h
import fixtures


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encode(value):
    if value is None:
        return b'N'
    if isinstance(value, bytes):
        return b'B' + len(value).to_bytes(8, 'little') + value
    if isinstance(value, str):
        return b'S' + value.encode()
    return b'V' + repr(value).encode()


def row_hash(batch, row, columns):
    digest = hashlib.sha256()
    for name in columns:
        value = encode(batch[name][row].as_py())
        digest.update(len(value).to_bytes(8, 'little'))
        digest.update(value)
    return digest.hexdigest()


def validate(directory):
    import lance
    import numpy as np
    import pyarrow as pa
    import pyarrow.ipc as ipc
    spec = read(directory / 'spec.json')
    metrics = read(directory / 'metrics.json')
    assert h.identity() == read(ROOT / 'fixtures.json')['validator_identity']
    task = spec['task']
    if task == 'merge':
        unchanged = metrics['status'] != 'success'
        if spec['workload'] in ('Wn', 'Ws', 'N_dense', 'R_admission'):
            result = fixtures.validate(fixtures.workloads()[spec['workload']], directory, unchanged)
        else:
            ds = lance.dataset(str(directory / 'dataset'))
            initial = read(directory / 'initial-snapshot.json')
            if unchanged:
                assert ds.version == initial['version']
            elif not spec.get('plan_only'):
                assert ds.version == initial['version'] + 1
            seen = set()
            if spec['workload'] == 'compressed_wide':
                from prepare import compressed_value, compressed_new
                for batch in ds.to_batches(batch_size=4, batch_readahead=1):
                    for i in range(batch.num_rows):
                        row = batch['id'][i].as_py()
                        assert row not in seen
                        seen.add(row)
                        assert batch['row_marker'][i].as_py() == row
                        assert batch['c0'][i].as_py() == row * 2
                        assert batch['c1'][i].as_py() == row * 3
                        assert batch['payload_binary'][i].as_py() == compressed_value(row, 'binary')
                        assert batch['payload_text'][i].as_py() == compressed_value(row, 'text')
                        assert batch['new_payload'][i].as_py() == compressed_new(row, not unchanged and row < 64)
                assert seen == set(range(128))
                counts = dict(num_updated_rows=64, num_inserted_rows=0, num_deleted_rows=0)
            else:
                for batch in ds.to_batches(batch_size=512):
                    for i in range(batch.num_rows):
                        row = batch['id'][i].as_py()
                        assert row not in seen
                        seen.add(row)
                        assert batch['c0'][i].as_py() == (row * 2 if unchanged else -row - 10)
                        assert batch['c1'][i].as_py() == (row * 3 if unchanged else -row - 20)
                assert seen == set(range(1000 if unchanged else 5000))
                counts = dict(num_updated_rows=1000, num_inserted_rows=4000, num_deleted_rows=0)
            if not unchanged:
                assert metrics['merge_stats'] == counts
            result = dict(validated=True, unchanged=unchanged, rows=len(seen), version=ds.version,
                          expected_counts=counts if not unchanged else None,
                          validated_field_names=ds.schema.names, oracle='all-fields-generated-values')
    elif task == 'repartition':
        assert metrics['status'] == 'success', metrics
        expected = {}
        with pa.memory_map(spec['source_ipc'], 'r') as stream:
            reader = ipc.open_file(stream)
            columns = reader.schema.names
            for index in range(reader.num_record_batches):
                batch = reader.get_batch(index)
                for row in range(batch.num_rows):
                    key = batch['id'][row].as_py()
                    assert key not in expected
                    expected[key] = row_hash(batch, row, columns)
        seen = set()
        distribution = []
        for path in sorted(directory.glob('output-*.arrow')):
            count = batches = 0
            with pa.memory_map(str(path), 'r') as stream:
                reader = ipc.open_file(stream)
                assert reader.schema.names == columns
                for index in range(reader.num_record_batches):
                    batch = reader.get_batch(index)
                    batches += 1
                    for row in range(batch.num_rows):
                        key = batch['id'][row].as_py()
                        assert key not in seen
                        seen.add(key)
                        assert row_hash(batch, row, columns) == expected[key]
                        count += 1
            partition = int(path.stem.split('-')[1])
            distribution.append(dict(partition=partition, rows=count, batches=batches))
        assert seen == set(expected)
        for actual in distribution:
            item = next(item for item in metrics['distribution'] if item['partition'] == actual['partition'])
            assert item['rows'] == actual['rows'] and item['batches'] == actual['batches']
        result = dict(validated=True, rows=len(seen), validated_field_names=columns,
                      distribution=distribution, oracle='all-source-field-row-sha256')
    elif task == 'take':
        assert metrics['status'] == 'success', metrics
        workload = fixtures.workloads()[spec['workload']]
        keys = fixtures.keys_for(workload)
        ds = lance.dataset(spec['fixture'])
        expected = ds.take(keys.tolist())
        columns = ds.schema.names
        missing = [name for name in columns if name not in ('id', 'c0', 'c1')]
        expected_hashes = {}
        for batch in expected.to_batches(max_chunksize=1024):
            for row in range(batch.num_rows):
                key = batch['id'][row].as_py()
                assert key not in expected_hashes
                expected_hashes[key] = row_hash(batch, row, missing)
        del expected
        seen = set()
        for path in sorted(directory.glob('output-*.arrow')):
            with pa.memory_map(str(path), 'r') as stream:
                reader = ipc.open_file(stream)
                assert set(columns).issubset(reader.schema.names)
                for index in range(reader.num_record_batches):
                    batch = reader.get_batch(index)
                    for row in range(batch.num_rows):
                        key = batch['id'][row].as_py()
                        assert key not in seen
                        seen.add(key)
                        assert batch['c0'][row].as_py() == -9505
                        assert batch['c1'][row].as_py() == -10077
                        assert batch['__action'][row].as_py() == 1
                        assert batch['__merge_source_sentinel'][row].as_py() is True
                        assert batch['_rowaddr'][row].as_py() is not None
                        assert row_hash(batch, row, missing) == expected_hashes[key]
        assert seen == set(expected_hashes)
        result = dict(validated=True, rows=len(seen), validated_field_names=columns,
                      oracle='independent-U-take-full-field-row-sha256', scope='join-and-payload-stage-only')
    else:
        raise AssertionError(task)
    result['validated_output_files'] = {str(path.relative_to(directory)): dict(sha256=sha(path), bytes=path.stat().st_size)
        for path in sorted(directory.glob('output-*.arrow'))}
    result['validator_identity'] = h.identity()
    save(directory / 'validate.json', result)


def init_freeze():
    artifacts = []
    for line in (ROOT / 'logs/build-artifacts.jsonl').read_text().splitlines():
        item = json.loads(line)
        if item.get('reason') == 'compiler-artifact' and item.get('executable') and item['target']['name'] == 'lance':
            artifacts.append(item)
    assert len(artifacts) == 1, [x.get('executable') for x in artifacts]
    binary = ROOT / 'bin/probe-v1'
    binary.parent.mkdir(exist_ok=True)
    assert not binary.exists()
    shutil.copy2(artifacts[0]['executable'], binary)
    subprocess.check_call(['git', '-C', str(CHECKOUT), 'add', '-N',
        'rust/lance/src/dataset/write/merge_insert/hypotheses.rs',
        'rust/lance/src/dataset/write/merge_insert/hypotheses/deferred_reference.rs'])
    patch = subprocess.check_output(['git', '-C', str(CHECKOUT), 'diff', 'HEAD', '--binary'])
    (ROOT / 'implementation.patch').write_bytes(patch)
    names = subprocess.check_output(['git', '-C', str(CHECKOUT), 'diff', '--name-only', 'HEAD'], text=True).splitlines()
    source_hashes = {}
    for name in names:
        source_hashes[name] = sha(CHECKOUT / name)
        copy = ROOT / 'snapshot' / name
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CHECKOUT / name, copy)
    harness_hashes = {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / 'scripts').glob('*')) if p.is_file()}
    freeze = dict(base_commit='0a0d327082988018a25f56147d3b6d02f6c79ecc', base_candidate='P 9e1ebc2e816a7195b56757ebe269e74989fc30c7 port',
        source_hashes=source_hashes, full_tree_identity=h.tree_identity(CHECKOUT),
        implementation_patch_sha256=sha(ROOT / 'implementation.patch'),
        binary=dict(path=str(binary), sha256=sha(binary), compiler_artifact=artifacts[0]),
        root_cargo_lock_sha256=sha(CHECKOUT / 'Cargo.lock'),
        harness_hashes=harness_hashes, fixture_identity_sha256=sha(ROOT / 'fixtures.json'),
        previous_harness_sha256=sha(OLD / 'harness/harness.py'),
        timing='New configuration probes; old merge API results are not pooled with these measurements.',
        captured_at=time.time())
    save(ROOT / 'freeze-v1.json', freeze)


def setup_sampler(directory):
    h.ROOT = ROOT
    def command(variant, *arguments):
        _, operation, _ = arguments
        if operation == 'execute':
            return ([read(ROOT / 'freeze-v1.json')['binary']['path'], '--exact',
                     'dataset::write::merge_insert::hypotheses::run_frozen_hypothesis', '--nocapture'], CHECKOUT)
        return (['/root/.local/bin/uv', 'run', '--no-sync', 'python', str(ROOT / 'scripts/run.py'),
                 'worker', str(directory)], U)
    h.command = command
    original_environment = h.environment
    def environment(variant, pool):
        result = original_environment(variant, pool)
        result['LANCE_HYPOTHESIS_SPEC'] = str(directory / 'spec.json')
        result['LANCE_HYPOTHESIS_TICKS'] = str(os.sysconf('SC_CLK_TCK'))
        result['RUST_TEST_THREADS'] = '1'
        return result
    h.environment = environment
    return original_environment


def run_case(name, spec):
    assert os.sysconf('SC_CLK_TCK') == 100, 'Rust /proc CPU conversion is pinned to the verified Linux HZ'
    h.no_builds()
    directory = ROOT / 'runs' / name
    directory.mkdir(exist_ok=False)
    save(directory / 'spec.json', spec)
    if spec['task'] == 'merge':
        h.clone_dataset(Path(spec['fixture']), directory / 'dataset')
        import lance
        ds = lance.dataset(str(directory / 'dataset'))
        save(directory / 'initial-snapshot.json', dict(version=ds.version, rows=ds.count_rows()))
    for path in Path(spec['fixture']).rglob('*.lance'):
        with path.open('rb') as stream:
            while stream.read(8 << 20):
                pass
    with Path(spec['source_ipc']).open('rb') as stream:
        while stream.read(8 << 20):
            pass
    original = setup_sampler(directory)
    try:
        resource = h.isolated('execute', 'Probe', directory, pool=spec['pool_bytes'], limit=8 << 30, timeout=900)
        assert resource['exit_code'] == 0 and not resource['confirmed_oom'], resource
        metrics = read(directory / 'metrics.json')
        assert metrics['status'] in ('success', 'execution_error', 'plan_only'), metrics
        validation = h.isolated('validate', 'Probe', directory, pool=1 << 30, limit=8 << 30, timeout=900)
        assert validation['exit_code'] == 0, validation
        record = dict(name=name, spec=spec, spec_sha256=sha(directory / 'spec.json'),
            freeze_sha256=sha(ROOT / 'freeze-v1.json'), metrics=metrics,
            validation=read(directory / 'validate.json'), resource=resource)
        save(directory / 'result.json', record)
        print(json.dumps(dict(name=name, status=metrics['status'], seconds=metrics.get('merge_seconds'),
            pool_peak=metrics['pool']['peak_reserved'], validated=True)), flush=True)
    finally:
        h.environment = original


def common(task, workload, source=None):
    prepared = read(ROOT / 'fixtures.json')
    return dict(task=task, workload=workload, fixture=str(ROOT / 'fixtures' / workload),
        source_ipc=prepared['sources'][source or workload]['path'], source_form='reader',
        pool_bytes=1 << 30, partitions=16, batch_size=8192, policy='p',
        join_reordering=True, repartition_joins=True, round_robin=True, statistics_registry=True)


def diagnostics():
    cases = []
    for form in ('complete', 'reader'):
        for policy in ('current', 'manifest', 'guard'):
            spec = common('merge', 'compressed_wide') | dict(source_form=form, policy=policy,
                pool_bytes=64 << 20, scan_batch_rows=8, scan_io_bytes=16 << 20)
            cases.append((f'h1-{form}-{policy}', spec))
    cases.append(('h1-reader-mask-only-plan', common('merge', 'compressed_wide') | dict(policy='mask_only',
        pool_bytes=64 << 20, scan_batch_rows=8, scan_io_bytes=16 << 20, plan_only=True)))
    for form in ('complete', 'reader'):
        cases.append((f'h1-reverse-{form}-guard', common('merge', 'fixed_reverse') | dict(policy='guard', source_form=form,
            pool_bytes=8 << 20, insert=True)))
    cases.append(('h1-original-reverse-guard-plan', common('merge', 'R_admission') | dict(policy='guard',
        pool_bytes=256 << 20, insert=True, plan_only=True)))
    for source in ('Ws', 'Ws_multi'):
        for variant, options in (
            ('p', dict(join_reordering=False, repartition_joins=False, round_robin=False)),
            ('parallel', dict(join_reordering=False, repartition_joins=True, round_robin=True)),
            ('parallel-small', dict(join_reordering=False, repartition_joins=True, round_robin=True, batch_size=1))):
            cases.append((f'h2-merge-{source}-{variant}', common('merge', 'Ws', source) | options))
    for source, batch, split in (('Ws', 8192, 0), ('Ws', 1, 0), ('Ws', 1, 16 << 20), ('Ws_multi', 8192, 0), ('Ws_multi', 1, 0)):
        spec = common('repartition', 'Ws', source) | dict(batch_size=batch, split_bytes=split)
        cases.append((f'h2-rr-{source}-batch{batch}-split{split}', spec))
    for workload in ('Wn', 'N_dense'):
        for mode in (('condition', 'generic') if workload == 'Wn' else ('early', 'condition', 'generic')):
            spec = common('take', workload) | dict(policy='current', take_mode=mode)
            cases.append((f'h3-{workload}-{mode}', spec))
    save(ROOT / 'diagnostic-plan.json', dict(seed=950510077, cells=[dict(name=n, spec=s) for n, s in cases],
        stop='No broad timing matrix. Failure invalidates a proposed strategy and is retained, not timed.'))
    for name, spec in cases:
        run_case(name, spec)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('freeze', 'diagnostics', 'worker', 'pairs'))
    parser.add_argument('path', nargs='?')
    args = parser.parse_args()
    if args.operation == 'worker':
        validate(Path(args.path))
    elif args.operation == 'freeze':
        init_freeze()
    elif args.operation == 'diagnostics':
        diagnostics()
    else:
        plan = read(args.path)
        for cell in plan['cells']:
            run_case(cell['name'], cell['spec'])


if __name__ == '__main__':
    main()
