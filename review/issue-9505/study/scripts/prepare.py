"""Prepare only the fixtures and source forms needed by the registered hypotheses."""
import hashlib
import json
import os
from pathlib import Path
import sys

import lance
import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc

ROOT = Path('/mnt/lance/hypotheses-9505-20261019')
OLD = Path('/mnt/lance/unified-9505-20261019')
sys.path.insert(0, str(OLD / 'harness'))
import fixtures
import harness


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest(path):
    return {str(p.relative_to(path)): digest(p) for p in sorted(path.rglob('*')) if p.is_file()}


def write_ipc(name, schema, batches):
    path = ROOT / 'fixtures' / f'{name}.arrow'
    if path.exists():
        raise FileExistsError(path)
    rows = count = logical = 0
    with path.open('wb') as output, ipc.new_file(output, schema) as writer:
        for batch in batches:
            writer.write_batch(batch)
            rows += batch.num_rows
            count += 1
            logical += batch.nbytes
    return dict(path=str(path), sha256=digest(path), rows=rows, batches=count, arrow_logical_bytes=logical)


def compressed_value(row, kind):
    size = 1 << 20
    prefix = f'{kind}:{row}:'.encode()
    value = (prefix + b'A' * size)[:size]
    return value.decode() if kind == 'text' else value


def compressed_new(row, source=False):
    return ((f'{"new" if source else "old"}:{row}:'.encode()) + b'B' * 8192)[:8192]


def main():
    imports = {}
    for name in ('Wn', 'Ws', 'N_dense'):
        original = harness.verify_fixture(name)
        path = ROOT / 'fixtures' / name
        path.symlink_to(OLD / 'fixtures' / name, target_is_directory=True)
        imports[name] = dict(original_root=str(OLD), manifest=original)
    sources = {}
    for name in ('Wn', 'Ws', 'N_dense'):
        spec = fixtures.workloads()[name]
        generation = ROOT / 'fixtures' / f'{name}-source-generation'
        generation.mkdir()
        schema = fixtures.schema(spec, source=True)
        sources[name] = write_ipc(name + '-source-single', schema, fixtures.source_batches(spec, generation))
        if name == 'Ws':
            with pa.memory_map(sources[name]['path'], 'r') as stream:
                reader = ipc.open_file(stream)
                def split():
                    for index in range(reader.num_record_batches):
                        batch = reader.get_batch(index)
                        for row in range(batch.num_rows):
                            yield batch.slice(row, 1)
                sources['Ws_multi'] = write_ipc('Ws-source-multi', schema, split())
    compression = {'lance-encoding:compression': 'zstd'}
    schema = pa.schema([
        ('id', pa.int64()), ('c0', pa.int64()), ('c1', pa.int64()),
        pa.field('payload_binary', pa.large_binary(), metadata=compression),
        pa.field('payload_text', pa.string(), metadata=compression),
        pa.field('new_payload', pa.large_binary(), metadata=compression),
        ('row_marker', pa.int64()),
    ])
    def target_batches():
        for first in range(0, 128, 8):
            ids = np.arange(first, first + 8, dtype=np.int64)
            yield pa.RecordBatch.from_pydict(dict(id=ids, c0=ids * 2, c1=ids * 3,
                payload_binary=[compressed_value(int(i), 'binary') for i in ids],
                payload_text=[compressed_value(int(i), 'text') for i in ids],
                new_payload=[compressed_new(int(i)) for i in ids], row_marker=ids), schema=schema)
    compressed_path = ROOT / 'fixtures' / 'compressed_wide'
    ds = lance.write_dataset(pa.RecordBatchReader.from_batches(schema, target_batches()), str(compressed_path),
        data_storage_version='2.2', max_rows_per_file=32, max_rows_per_group=8)
    source_schema = pa.schema([('id', pa.int64()), schema.field('new_payload')])
    batch = pa.RecordBatch.from_pydict(dict(id=np.arange(64, dtype=np.int64),
        new_payload=[compressed_new(i, True) for i in range(64)]), schema=source_schema)
    sources['compressed_wide'] = write_ipc('compressed-wide-source', source_schema, [batch])
    fixed_schema = pa.schema([('id', pa.int64()), ('c0', pa.int64()), ('c1', pa.int64())])
    ids = np.arange(1000, dtype=np.int64)
    small = pa.RecordBatch.from_pydict(dict(id=ids, c0=ids * 2, c1=ids * 3), schema=fixed_schema)
    fixed_path = ROOT / 'fixtures' / 'fixed_reverse'
    lance.write_dataset(small, str(fixed_path), data_storage_version='2.2', max_rows_per_file=250)
    ids = np.arange(5000, dtype=np.int64)
    large = pa.RecordBatch.from_pydict(dict(id=ids, c0=-ids-10, c1=-ids-20), schema=fixed_schema)
    sources['fixed_reverse'] = write_ipc('fixed-reverse-source', fixed_schema, large.to_batches() if hasattr(large, 'to_batches') else [large])
    generated = {name: dict(path=str(ROOT / 'fixtures' / name), files=manifest(ROOT / 'fixtures' / name))
                 for name in ('compressed_wide', 'fixed_reverse')}
    identity = harness.identity()
    result = dict(generator_sha256=digest(Path(__file__)), validator_identity=identity,
        imported=imports, generated=generated, sources=sources,
        compressed_target=dict(rows=ds.count_rows(), logical_payload_bytes=128 * 2 * (1 << 20),
            data_file_bytes=sum(p.stat().st_size for p in compressed_path.rglob('*.lance'))),
        source_scope='IPC source values match frozen generators. Complete input materializes before the timer; unknown reader decodes IPC lazily during execution.')
    (ROOT / 'fixtures.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
