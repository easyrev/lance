# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright The Lance Authors

"""Generate the target table and the source tiers (run once, shared by both builds).

    python datagen.py target
    python datagen.py source 128m 1g 4g [16g]
"""

from __future__ import annotations

import json
import os
import sys
import time

import lance
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as pads
import pyarrow.parquet as pq

from common import (
    BASE_TAG,
    DATA,
    GEN_BATCH_ROWS,
    INDEXED_TAG,
    PARQUET_ROWS_PER_FILE,
    PARQUET_ROWS_PER_GROUP,
    SAMPLE_EXISTING,
    SAMPLE_NEW,
    TARGET_ROWS,
    TARGET_ROWS_PER_FRAGMENT,
    TARGET_URI,
    lance_source_uri,
    make_batch,
    meta_path,
    parquet_source_dir,
    sample_path,
    schema,
    tier_rows,
)


def dir_bytes(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
    return total


def gen_target() -> None:
    rng = np.random.default_rng(7895)

    def batches():
        for start in range(0, TARGET_ROWS, GEN_BATCH_ROWS):
            ids = np.arange(start, min(start + GEN_BATCH_ROWS, TARGET_ROWS))
            yield make_batch(ids, rng, "t")

    t0 = time.monotonic()
    reader = pa.RecordBatchReader.from_batches(schema(), batches())
    ds = lance.write_dataset(
        reader, TARGET_URI, mode="create", max_rows_per_file=TARGET_ROWS_PER_FRAGMENT
    )
    ds.tags.create(BASE_TAG, ds.version)
    ds.create_scalar_index("id", "BTREE")
    ds = lance.dataset(TARGET_URI)
    ds.tags.create(INDEXED_TAG, ds.version)
    assert ds.count_rows() == TARGET_ROWS
    print(
        json.dumps(
            {
                "target_uri": TARGET_URI,
                "rows": TARGET_ROWS,
                "fragments": len(ds.get_fragments()),
                "bytes_on_disk": dir_bytes(TARGET_URI),
                "tags": {k: v["version"] for k, v in ds.tags.list().items()},
                "lance_version": lance.__version__,
                "seconds": round(time.monotonic() - t0, 1),
            }
        )
    )


def gen_source(tier: str) -> None:
    n = tier_rows(tier)
    n_existing = n // 2
    n_new = n - n_existing
    rng = np.random.default_rng(sum(map(ord, tier)) * 9617)
    existing = rng.choice(TARGET_ROWS, n_existing, replace=False)
    new = TARGET_ROWS + np.arange(n_new)
    ids = np.concatenate([existing, new])
    rng.shuffle(ids)

    # The competing commit updates one existing key that the source also
    # updates, so the conflict is row-level and must be retried, and the
    # retried merge must overwrite the competitor's value.
    competitor_id = int(existing[0])
    sample_ids = np.concatenate(
        [existing[1 : 1 + SAMPLE_EXISTING], new[:SAMPLE_NEW], [competitor_id]]
    )
    sample_set = pa.array(sample_ids, pa.int64())

    pdir = parquet_source_dir(tier)
    os.makedirs(pdir, exist_ok=False)
    t0 = time.monotonic()
    arrow_bytes = 0
    samples = []
    writer = None
    file_index = 0
    rows_in_file = 0
    for start in range(0, n, GEN_BATCH_ROWS):
        batch = make_batch(ids[start : start + GEN_BATCH_ROWS], rng, f"s{tier}")
        arrow_bytes += batch.nbytes
        hit = batch.filter(pc.is_in(batch["id"], value_set=sample_set))
        if hit.num_rows:
            samples.append(hit)
        if writer is None:
            writer = pq.ParquetWriter(
                os.path.join(pdir, f"part-{file_index:05d}.parquet"), schema()
            )
        writer.write_batch(batch, row_group_size=PARQUET_ROWS_PER_GROUP)
        rows_in_file += batch.num_rows
        if rows_in_file >= PARQUET_ROWS_PER_FILE:
            writer.close()
            writer = None
            file_index += 1
            rows_in_file = 0
    if writer is not None:
        writer.close()

    # Lance copy is written from the Parquet rows so both formats are identical.
    parquet_ds = pads.dataset(pdir, format="parquet")
    lance_uri = lance_source_uri(tier)
    src = lance.write_dataset(
        parquet_ds.scanner().to_reader(), lance_uri, mode="create", schema=schema()
    )
    assert src.version == 1 and src.count_rows() == n

    sample = pa.Table.from_batches(samples, schema=schema()).sort_by("id")
    assert sample.num_rows == len(sample_ids)
    pq.write_table(sample, sample_path(tier))

    meta = {
        "tier": tier,
        "rows": n,
        "existing_keys": n_existing,
        "new_keys": n_new,
        "arrow_bytes": arrow_bytes,
        "lance_bytes_on_disk": dir_bytes(lance_uri),
        "lance_fragments": len(src.get_fragments()),
        "parquet_bytes_on_disk": dir_bytes(pdir),
        "parquet_files": len(os.listdir(pdir)),
        "competitor_id": competitor_id,
        "lance_version": lance.__version__,
        "seconds": round(time.monotonic() - t0, 1),
    }
    with open(meta_path(tier), "w") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta))


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    if sys.argv[1] == "target":
        gen_target()
    elif sys.argv[1] == "source":
        for tier in sys.argv[2:]:
            gen_source(tier)
    else:
        raise SystemExit(__doc__)
