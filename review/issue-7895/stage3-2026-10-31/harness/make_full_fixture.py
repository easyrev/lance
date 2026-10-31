#!/usr/bin/env python3
"""Create the Experiment 1 target and the 1, 4, and 16 GiB sources."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import lance
import numpy as np
import pyarrow as pa


def load_helpers():
    path = Path(__file__).with_name("make_pilot_fixture.py")
    spec = importlib.util.spec_from_file_location("pilot_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["pilot_helpers"] = module
    spec.loader.exec_module(module)
    return module


def write_reader(reader, path: Path) -> None:
    lance.write_dataset(
        reader,
        path,
        max_rows_per_file=1_048_576,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--target-rows", type=int, default=4_000_000)
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--seed", type=int, default=9617)
    parser.add_argument(
        "--source-gibs",
        type=int,
        nargs="+",
        default=[1, 4, 16],
    )
    args = parser.parse_args()

    helpers = load_helpers()
    args.root.mkdir(parents=True, exist_ok=True)
    target_path = args.root / "target.lance"
    if not target_path.exists():
        target_ids = np.arange(args.target_rows, dtype=np.int64)
        write_reader(
            pa.RecordBatchReader.from_batches(
                helpers.full_schema(),
                helpers.full_batches(target_ids, args.batch_size, args.seed),
            ),
            target_path,
        )
        target = lance.dataset(target_path)
        target.tags.create("bench-base", target.version)

    bytes_per_row = 8 + helpers.VECTOR_DIM * 4 + 16 + 8
    fixture: dict[str, object] = {
        "target_rows": args.target_rows,
        "sources": {},
    }
    for source_gib in args.source_gibs:
        source_rows = int((source_gib * 1024**3) / bytes_per_row)
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
        lance_path = args.root / f"source-{source_gib}gib.lance"
        parquet_path = args.root / f"source-{source_gib}gib.parquet"
        if not lance_path.exists():
            write_reader(
                pa.RecordBatchReader.from_batches(
                    helpers.full_schema(),
                    helpers.full_batches(
                        source_ids,
                        args.batch_size,
                        args.seed + 1,
                        label_prefix="updated",
                    ),
                ),
                lance_path,
            )
        if not parquet_path.exists():
            helpers.write_parquet(
                parquet_path,
                helpers.full_batches(
                    source_ids,
                    args.batch_size,
                    args.seed + 1,
                    label_prefix="updated",
                ),
                args.batch_size,
            )
        fixture["sources"][str(source_gib)] = {
            "rows": source_rows,
            "expected_rows_after": args.target_rows + source_rows // 2,
        }

    samples = [
        helpers.full_expected(0, args.seed + 1, label_prefix="updated"),
        helpers.full_expected(
            args.target_rows - 1,
            args.seed,
            label_prefix="label",
        ),
        helpers.full_expected(
            args.target_rows,
            args.seed + 1,
            label_prefix="updated",
        ),
    ]
    (args.root / "expected-samples.json").write_text(
        json.dumps(
            {str(row["id"]): row for row in samples},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    fixture["sample_ids"] = [row["id"] for row in samples]
    fixture["columns"] = ["id", "vector", "label", "timestamp"]
    (args.root / "fixture.json").write_text(
        json.dumps(fixture, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(fixture, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
