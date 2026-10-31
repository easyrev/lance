#!/usr/bin/env python3
"""Create deterministic benchmark specs and sampled expected rows."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--target-uri", required=True)
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--source-format", choices=("lance", "parquet"), required=True)
    parser.add_argument("--base-rows", type=int, required=True)
    parser.add_argument("--source-rows", type=int, required=True)
    parser.add_argument("--expected-rows-after", type=int, required=True)
    parser.add_argument("--conflict-id", type=int, required=True)
    parser.add_argument("--sample-ids", required=True)
    parser.add_argument("--expected-rows", type=Path, required=True)
    parser.add_argument("--columns", required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--storage", choices=("local", "oss"), default="local")
    parser.add_argument(
        "--write-mode",
        choices=("auto", "rewrite_rows", "rewrite_columns"),
        default="auto",
    )
    args = parser.parse_args()

    expected = json.loads(args.expected_rows.read_text(encoding="utf-8"))
    columns = json.loads(args.columns)
    samples = []
    for identifier in json.loads(args.sample_ids):
        row = expected[str(identifier)]
        samples.append(
            {
                "id": identifier,
                "columns": [
                    {"name": column, "value": row[column]} for column in columns
                ],
            }
        )
    spec = {
        "target_uri": args.target_uri,
        "source_uri": args.source_uri,
        "source_format": args.source_format,
        "base_rows": args.base_rows,
        "source_rows": args.source_rows,
        "expected_rows_after": args.expected_rows_after,
        "conflict_id": args.conflict_id,
        "samples": samples,
        "experiment": args.experiment,
        "case": args.case,
        "storage": args.storage,
        "write_mode": args.write_mode,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
