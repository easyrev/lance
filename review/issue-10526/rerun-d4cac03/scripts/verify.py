"""Compare the scan and a single full-permutation take with the input IPC."""
import hashlib
import json
import sys
from pathlib import Path

import lance
import numpy as np
import pyarrow as pa

dataset_path, input_path = map(Path, sys.argv[1:])
dataset = lance.dataset(dataset_path)
with pa.memory_map(str(input_path), "r") as source:
    expected = pa.ipc.open_file(source).get_batch(0)
    offset = 0
    for batch in dataset.to_batches(batch_size=1024):
        assert batch.equals(expected.slice(offset, batch.num_rows)), ("scan", offset)
        offset += batch.num_rows
    assert offset == expected.num_rows

    indices = np.random.default_rng(10526).permutation(expected.num_rows)
    actual = dataset.take(indices.tolist())
    assert actual.num_rows == len(indices)
    for start in range(0, len(indices), 1024):
        wanted = expected.take(pa.array(indices[start : start + 1024]))
        observed = actual.slice(start, wanted.num_rows)
        assert observed.equals(pa.Table.from_batches([wanted])), ("take", start)

    print(json.dumps({
        "dataset": dataset_path.name,
        "scan_rows": offset,
        "take_rows": len(indices),
        "take_calls": 1,
        "take_seed": 10526,
        "take_indices_sha256": hashlib.sha256(indices.astype("<i8", copy=False)).hexdigest(),
        "matched": True,
    }))
