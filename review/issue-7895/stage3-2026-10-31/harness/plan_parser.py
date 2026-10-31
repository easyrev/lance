#!/usr/bin/env python3
"""Extract hash-join and memory fields from an analyzed physical plan."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

COUNT_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<suffix>[KMGTP]?B|[KMGTP])?"
)


def parse_count(token: str) -> int:
    match = COUNT_PATTERN.search(token)
    if not match:
        raise ValueError(f"cannot parse count: {token}")
    scale = {
        "": 1,
        "B": 1,
        "K": 1_000,
        "M": 1_000_000,
        "G": 1_000_000_000,
        "T": 1_000_000_000_000,
        "KB": 1_000,
        "MB": 1_000_000,
        "GB": 1_000_000_000,
        "TB": 1_000_000_000_000,
        "PB": 1_000_000_000_000_000,
    }[match.group("suffix")]
    return int(float(match.group("value")) * scale)


def parse_field(line: str, name: str) -> str | None:
    match = re.search(rf"(?:^|[, ]){re.escape(name)}=([^,\]]+)", line)
    return match.group(1).strip() if match else None


def main(path_value: str, source_rows: int, target_rows: int) -> int:
    path = Path(path_value)
    plan = path.read_text(encoding="utf-8")
    lines = plan.splitlines()
    join_line = next(
        (line for line in lines if "HashJoinExec:" in line),
        None,
    )
    if join_line is None:
        raise ValueError(f"no HashJoinExec in {path}")

    build_rows_text = parse_field(join_line, "build_input_rows")
    build_memory_text = parse_field(join_line, "build_mem_used")
    if build_rows_text is None or build_memory_text is None:
        raise ValueError(f"missing hash-join metrics in {path}")
    build_rows = parse_count(build_rows_text)
    build_memory = parse_count(build_memory_text)
    if abs(build_rows - source_rows) < abs(build_rows - target_rows):
        build_side = "source"
    else:
        build_side = "target"

    result = {
        "plan_path": str(path),
        "join_mode": parse_field(join_line, "mode"),
        "join_type": parse_field(join_line, "join_type"),
        "build_side": build_side,
        "build_input_rows": build_rows,
        "build_input_rows_text": build_rows_text,
        "build_mem_used_bytes": build_memory,
        "build_mem_used_text": build_memory_text,
        "native_source_read": "uri=mnt/lance/9617-bench" in join_line
        or any(
            "LanceRead:" in line and "source-" in line
            for line in lines
        )
        or any(
            "LanceRead:" in line and "/source" in line
            for line in lines
        ),
        "streaming_source": any(
            "StreamingTableExec" in line for line in lines
        ),
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3])))
