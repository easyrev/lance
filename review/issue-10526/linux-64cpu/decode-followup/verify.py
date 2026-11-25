import json
import sys
from pathlib import Path

import lance
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

dataset_path, input_path = map(Path, sys.argv[1:])
dataset = lance.dataset(dataset_path)
with pa.memory_map(str(input_path), "r") as source:
    expected = pa.ipc.open_file(source).get_batch(0)
    offset = 0
    for batch in dataset.to_batches(batch_size=1024):
        assert batch.equals(expected.slice(offset, batch.num_rows)), offset
        offset += batch.num_rows
    assert offset == expected.num_rows

    # Every row is selected exactly once, in a deterministic nonsequential order.
    indices = np.random.default_rng(10526).permutation(expected.num_rows)
    for start in range(0, len(indices), 1024):
        rows = indices[start : start + 1024]
        wanted = expected.take(pa.array(rows))
        actual = dataset.take(rows.tolist())
        assert actual.num_rows == len(rows)
        if isinstance(actual, pa.RecordBatch):
            assert actual.equals(wanted), start
        else:
            assert actual.equals(pa.Table.from_batches([wanted])), start

    column = expected.column(0)
    lengths = pc.binary_length(column)
    print(
        json.dumps(
            {
                "dataset": input_path.stem,
                "scan_rows": offset,
                "take_rows": len(indices),
                "batch_size": 1024,
                "take_seed": 10526,
                "null_rows": column.null_count,
                "empty_rows": pc.sum(pc.equal(lengths, 0)).as_py(),
                "short_nonempty_rows": pc.sum(
                    pc.and_(pc.greater(lengths, 0), pc.less(lengths, 180_000))
                ).as_py(),
            }
        )
    )
