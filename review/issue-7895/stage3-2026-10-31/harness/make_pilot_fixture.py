#!/usr/bin/env python3
"""Create one deterministic pilot target and full-size schema sources."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import lance
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


MASK32 = np.uint64(0xFFFFFFFF)
EPOCH = datetime(2026, 1, 1)
VECTOR_DIM = 768


def vector_for(ids: np.ndarray, seed: int) -> pa.Array:
    dimensions = np.arange(VECTOR_DIM, dtype=np.uint64)
    identifiers = ids.astype(np.uint64)[:, None]
    bits = (
        identifiers * np.uint64(2_654_435_761)
        + dimensions * np.uint64(2_246_822_519)
        + np.uint64(seed)
    ) & MASK32
    bits ^= bits >> np.uint64(16)
    bits *= np.uint64(2_246_822_519)
    bits &= MASK32
    values = (
        (bits >> np.uint64(8)).astype(np.float32) / np.float32(16_777_215.0)
    ) * np.float32(2.0) - np.float32(1.0)
    return pa.FixedSizeListArray.from_arrays(
        pa.array(values.reshape(-1), type=pa.float32()),
        list_size=VECTOR_DIM,
    )


def caption_for(identifier: int) -> str:
    stem = f"{identifier:016x}-"
    return (stem * (200 // len(stem) + 1))[:200]


def embedded_vector(identifier: int, dimension: int, seed: int) -> float:
    bits = (
        int(identifier) * 2_654_435_761
        + dimension * 2_246_822_519
        + seed
    ) & 0xFFFFFFFF
    bits ^= bits >> 16
    bits = (bits * 2_246_822_519) & 0xFFFFFFFF
    return float(
        np.float32(bits >> 8) / np.float32(16_777_215.0) * np.float32(2.0)
        - np.float32(1.0)
    )


def full_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("vector", pa.list_(pa.float32(), VECTOR_DIM)),
            pa.field("label", pa.string()),
            pa.field("timestamp", pa.timestamp("us")),
        ]
    )


def wide_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("embedding", pa.list_(pa.float32(), VECTOR_DIM)),
            pa.field("caption", pa.string()),
            pa.field("label", pa.string()),
            pa.field("score", pa.float32()),
        ]
    )


def partial_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("label", pa.string()),
            pa.field("score", pa.float32()),
        ]
    )


def full_batches(
    ids: np.ndarray,
    batch_size: int,
    seed: int,
    label_prefix: str = "label",
):
    schema = full_schema()
    for start in range(0, len(ids), batch_size):
        part = ids[start : start + batch_size]
        timestamps = np.asarray(
            [
                int(
                    (
                        EPOCH
                        + timedelta(microseconds=int(identifier) * 1000)
                        - datetime(1970, 1, 1)
                    ).total_seconds()
                    * 1e6
                )
                for identifier in part
            ],
            dtype=np.int64,
        )
        yield pa.RecordBatch.from_arrays(
            [
                pa.array(part, type=pa.int64()),
                vector_for(part, seed),
                pa.array(
                    [
                        f"{label_prefix}-{int(identifier) % 1024}"
                        for identifier in part
                    ],
                    type=pa.string(),
                ),
                pa.array(timestamps, type=pa.timestamp("us")),
            ],
            schema=schema,
        )


def wide_batches(ids: np.ndarray, batch_size: int, seed: int):
    schema = wide_schema()
    for start in range(0, len(ids), batch_size):
        part = ids[start : start + batch_size]
        yield pa.RecordBatch.from_arrays(
            [
                pa.array(part, type=pa.int64()),
                vector_for(part, seed),
                pa.array([caption_for(int(identifier)) for identifier in part]),
                pa.array(
                    [f"label-{int(identifier) % 1024}" for identifier in part],
                    type=pa.string(),
                ),
                pa.array(
                    [
                        float(np.float32((int(identifier) % 10000) / 10000))
                        for identifier in part
                    ],
                    type=pa.float32(),
                ),
            ],
            schema=schema,
        )


def partial_batches(ids: np.ndarray, batch_size: int):
    schema = partial_schema()
    for start in range(0, len(ids), batch_size):
        part = ids[start : start + batch_size]
        yield pa.RecordBatch.from_arrays(
            [
                pa.array(part, type=pa.int64()),
                pa.array(
                    [f"updated-{int(identifier) % 1024}" for identifier in part],
                    type=pa.string(),
                ),
                pa.array(
                    [
                        float(np.float32(1 + (int(identifier) % 10000) / 10000))
                        for identifier in part
                    ],
                    type=pa.float32(),
                ),
            ],
            schema=schema,
        )


def write_parquet(path: Path, reader, batch_size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    try:
        for batch in reader:
            if writer is None:
                writer = pq.ParquetWriter(path, batch.schema)
            writer.write_batch(batch)
    finally:
        if writer is not None:
            writer.close()


def full_expected(
    identifier: int,
    seed: int,
    *,
    label_prefix: str,
) -> dict:
    timestamp = EPOCH + timedelta(microseconds=identifier * 1000)
    return {
        "id": identifier,
        "vector": [
            embedded_vector(identifier, dimension, seed)
            for dimension in range(VECTOR_DIM)
        ],
        "label": f"{label_prefix}-{identifier % 1024}",
        "timestamp": timestamp.isoformat(sep=" "),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--kind", choices=("full", "wide"), required=True)
    parser.add_argument("--target-rows", type=int, required=True)
    parser.add_argument("--target-gib", type=float, default=0)
    parser.add_argument("--source-gib", type=float, default=0)
    parser.add_argument("--partial-source-rows", type=int, default=100_000)
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--seed", type=int, default=9617)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    target_path = args.root / "target.lance"
    source_lance_path = args.root / "source.lance"
    source_parquet_path = args.root / "source.parquet"
    expected_path = args.root / "expected-samples.json"
    target_ids = np.arange(args.target_rows, dtype=np.int64)

    if args.kind == "full":
        target_reader = pa.RecordBatchReader.from_batches(
            full_schema(),
            full_batches(target_ids, args.batch_size, args.seed),
        )
        bytes_per_row = 8 + VECTOR_DIM * 4 + 16 + 8
        source_rows = int((args.source_gib * 1024**3) / bytes_per_row)
        source_rows -= source_rows % 2
        updates = source_rows // 2
        source_ids = np.concatenate(
            [
                np.arange(updates, dtype=np.int64),
                np.arange(
                    args.target_rows,
                    args.target_rows + source_rows - updates,
                    dtype=np.int64,
                ),
            ]
        )
        source_lance_reader = pa.RecordBatchReader.from_batches(
            full_schema(),
            full_batches(
                source_ids,
                args.batch_size,
                args.seed + 1,
                label_prefix="updated",
            ),
        )
        source_parquet_reader = pa.RecordBatchReader.from_batches(
            full_schema(),
            full_batches(
                source_ids,
                args.batch_size,
                args.seed + 1,
                label_prefix="updated",
            ),
        )
        samples = [
            full_expected(
                0,
                args.seed + 1,
                label_prefix="updated",
            ),
            full_expected(
                args.target_rows - 1,
                args.seed,
                label_prefix="label",
            ),
            full_expected(
                args.target_rows,
                args.seed + 1,
                label_prefix="updated",
            ),
        ]
        columns = ["id", "vector", "label", "timestamp"]
    else:
        target_reader = pa.RecordBatchReader.from_batches(
            wide_schema(),
            wide_batches(target_ids, args.batch_size, args.seed),
        )
        source_rows = min(args.partial_source_rows, args.target_rows)
        source_ids = np.arange(source_rows, dtype=np.int64)
        source_lance_reader = pa.RecordBatchReader.from_batches(
            partial_schema(),
            partial_batches(source_ids, args.batch_size),
        )
        source_parquet_reader = pa.RecordBatchReader.from_batches(
            partial_schema(),
            partial_batches(source_ids, args.batch_size),
        )
        updated_label = f"updated-{0 % 1024}"
        samples = [
            {
                "id": 0,
                "embedding": [
                    embedded_vector(0, dimension, args.seed)
                    for dimension in range(VECTOR_DIM)
                ],
                "caption": caption_for(0),
                "label": updated_label,
                "score": float(np.float32(1.0)),
            },
            {
                "id": args.target_rows - 1,
                "embedding": [
                    embedded_vector(args.target_rows - 1, dimension, args.seed)
                    for dimension in range(VECTOR_DIM)
                ],
                "caption": caption_for(args.target_rows - 1),
                "label": f"label-{(args.target_rows - 1) % 1024}",
                "score": float(
                    np.float32(((args.target_rows - 1) % 10000) / 10000)
                ),
            },
        ]
        columns = ["id", "embedding", "caption", "label", "score"]

    target = lance.write_dataset(
        target_reader,
        target_path,
        max_rows_per_file=1_048_576,
    )
    target.tags.create("bench-base", target.version)
    lance.write_dataset(
        source_lance_reader,
        source_lance_path,
        max_rows_per_file=1_048_576,
    )
    write_parquet(source_parquet_path, source_parquet_reader, args.batch_size)

    expected_path.write_text(
        json.dumps(
            {str(row["id"]): row for row in samples},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    result = {
        "root": str(args.root),
        "kind": args.kind,
        "target_rows": args.target_rows,
        "source_rows": source_rows,
        "sample_ids": [row["id"] for row in samples],
        "columns": columns,
        "expected_versions_after_no_conflict": 3,
        "expected_rows_after": (
            args.target_rows + source_rows // 2
            if args.kind == "full"
            else args.target_rows
        ),
    }
    (args.root / "fixture.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
