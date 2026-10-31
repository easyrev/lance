#!/usr/bin/env python3
"""Create a small deterministic fixture for harness validation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import lance
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


EPOCH = datetime(2026, 1, 1)
VECTOR_DIM = 768


def full_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("vector", pa.list_(pa.float32(), VECTOR_DIM)),
            pa.field("label", pa.string()),
            pa.field("timestamp", pa.timestamp("us")),
        ]
    )


def vector_for(ids: np.ndarray) -> pa.Array:
    dimensions = np.arange(VECTOR_DIM, dtype=np.int64)
    values = (
        ((ids[:, None] * 131 + dimensions[None, :] * 17) % 1000).astype(
            np.float32
        )
        / np.float32(1000)
    )
    fixed = pa.FixedSizeListArray.from_arrays(
        pa.array(values.reshape(-1), type=pa.float32()),
        list_size=VECTOR_DIM,
    )
    return fixed


def full_batches(ids: np.ndarray, batch_size: int):
    schema = full_schema()
    for start in range(0, len(ids), batch_size):
        part = ids[start : start + batch_size]
        timestamp_values = np.asarray(
            [
                int(
                    (
                        (EPOCH + timedelta(microseconds=int(identifier) * 1000))
                        - datetime(1970, 1, 1)
                    ).total_seconds()
                    * 1e6
                )
                for identifier in part
            ],
            dtype=np.int64,
        )
        batch = pa.RecordBatch.from_arrays(
            [
                pa.array(part, type=pa.int64()),
                vector_for(part),
                pa.array([f"label-{int(identifier) % 1024}" for identifier in part]),
                pa.array(timestamp_values, type=pa.timestamp("us")),
            ],
            schema=schema,
        )
        yield batch


def write_source_parquet(path: Path, ids: np.ndarray, batch_size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    try:
        for batch in full_batches(ids, batch_size):
            if writer is None:
                writer = pq.ParquetWriter(path, batch.schema)
            writer.write_batch(batch)
    finally:
        if writer is not None:
            writer.close()


def expected_row(identifier: int) -> dict:
    vector = np.asarray(
        [
            float(np.float32(((identifier * 131 + dimension * 17) % 1000) / 1000))
            for dimension in range(VECTOR_DIM)
        ]
    ).tolist()
    timestamp = EPOCH + timedelta(microseconds=identifier * 1000)
    return {
        "id": identifier,
        "vector": vector,
        "label": f"label-{identifier % 1024}",
        "timestamp": timestamp.isoformat(sep=" "),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base-rows", type=int, default=16_384)
    parser.add_argument("--update-rows", type=int, default=1_024)
    parser.add_argument("--insert-rows", type=int, default=1_024)
    parser.add_argument("--batch-size", type=int, default=4_096)
    args = parser.parse_args()

    args.root.mkdir(parents=True, exist_ok=True)
    target_path = args.root / "target.lance"
    lance_source_path = args.root / "source.lance"
    parquet_source_path = args.root / "source.parquet"
    expected_path = args.root / "expected-samples.json"

    base_ids = np.arange(args.base_rows, dtype=np.int64)
    target = lance.write_dataset(
        pa.RecordBatchReader.from_batches(
            full_schema(),
            full_batches(base_ids, args.batch_size),
        ),
        target_path,
        max_rows_per_file=65_536,
    )
    target.tags.create("bench-base", 1)

    update_ids = np.arange(args.update_rows, dtype=np.int64)
    insert_ids = np.arange(
        args.base_rows,
        args.base_rows + args.insert_rows,
        dtype=np.int64,
    )
    source_ids = np.concatenate([update_ids, insert_ids]).astype(np.int64)
    source_schema = full_schema()
    lance.write_dataset(
        pa.RecordBatchReader.from_batches(
            source_schema,
            full_batches(source_ids, args.batch_size),
        ),
        lance_source_path,
        max_rows_per_file=65_536,
    )
    write_source_parquet(parquet_source_path, source_ids, args.batch_size)

    samples = [
        expected_row(int(update_ids[0])),
        expected_row(args.base_rows - 1),
        expected_row(int(insert_ids[0])),
    ]
    expected_path.write_text(
        json.dumps(
            {str(row["id"]): row for row in samples},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "root": str(args.root),
                "base_rows": args.base_rows,
                "source_rows": len(source_ids),
                "update_rows": args.update_rows,
                "insert_rows": args.insert_rows,
                "sample_ids": [row["id"] for row in samples],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
