# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright The Lance Authors

"""Shared layout for the PR #9617 replay-source scaling benchmark.

The target is an embedding-backfill table: 4M rows of
``id: int64, vec: fixed_size_list<float32, 768>, label: string(32), ts``
(~3.1 KB/row, ~11.6 GiB).  Each source tier holds 50% keys that already exist
in the target (updated) and 50% new keys (inserted), in random order, written
once as a Lance dataset and once as a Parquet directory with identical rows.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path("/mnt/lance/bench-9617")
DATA = ROOT / "data"
RESULTS = ROOT / "results"
TMP = ROOT / "tmp"

TARGET_URI = str(DATA / "target.lance")
# Pristine target without an index (DataFusion path), and with a BTREE on `id`
# (legacy indexed path).  Runs restore to one of these before every measurement.
BASE_TAG = "merge_insert_base"
INDEXED_TAG = "merge_insert_base_indexed"

TARGET_ROWS = 4_000_000
TARGET_ROWS_PER_FRAGMENT = 250_000
DIM = 768
LABEL_LEN = 32
# Arrow in-memory bytes per row: id + vec + label values + label offset + ts.
ROW_BYTES = 8 + DIM * 4 + LABEL_LEN + 4 + 8

TIERS = {
    "128m": 128 << 20,
    "1g": 1 << 30,
    "4g": 4 << 30,
    "16g": 16 << 30,
}

GEN_BATCH_ROWS = 65_536
PARQUET_ROWS_PER_FILE = 131_072
PARQUET_ROWS_PER_GROUP = 16_384

# Rows of each source kept aside to check merged values after every run.
SAMPLE_EXISTING = 64
SAMPLE_NEW = 16


def tier_rows(tier: str) -> int:
    return round(TIERS[tier] / ROW_BYTES)


def lance_source_uri(tier: str) -> str:
    return str(DATA / f"src-{tier}.lance")


def parquet_source_dir(tier: str) -> str:
    return str(DATA / f"src-{tier}.parquet")


def sample_path(tier: str) -> str:
    return str(DATA / f"src-{tier}-sample.parquet")


def meta_path(tier: str) -> str:
    return str(DATA / f"src-{tier}.json")


def schema():
    import pyarrow as pa

    return pa.schema(
        [
            ("id", pa.int64()),
            ("vec", pa.list_(pa.float32(), DIM)),
            ("label", pa.string()),
            ("ts", pa.timestamp("us")),
        ]
    )


def make_batch(ids, rng, prefix: str):
    """Rows for ``ids``; ``prefix`` makes source values distinguishable."""
    import numpy as np
    import pyarrow as pa

    n = len(ids)
    vec = rng.random((n, DIM), dtype=np.float32)
    labels = [f"{prefix}-{i:012d}".ljust(LABEL_LEN, "x")[:LABEL_LEN] for i in ids]
    ts = pa.array(np.asarray(ids, dtype=np.int64) + 1_700_000_000_000_000, pa.int64())
    return pa.record_batch(
        [
            pa.array(ids, pa.int64()),
            pa.FixedSizeListArray.from_arrays(pa.array(vec.ravel()), DIM),
            pa.array(labels, pa.string()),
            ts.cast(pa.timestamp("us")),
        ],
        schema=schema(),
    )
