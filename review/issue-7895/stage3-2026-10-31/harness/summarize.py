#!/usr/bin/env python3
"""Summarize run JSON with median, minimum, and maximum."""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def main(paths: list[str]) -> int:
    groups: dict[tuple[str, str, str, bool], list[dict]] = defaultdict(list)
    roots = [Path(value) for value in paths]
    files = []
    for root in roots:
        files.extend(root.glob("*.json") if root.is_dir() else [root])
    for path in sorted(set(files)):
        payload = json.loads(path.read_text(encoding="utf-8"))
        child = payload.get("child", {})
        key = (
            str(child.get("experiment")),
            str(child.get("case")),
            str(child.get("build")),
            bool(child.get("conflict")),
        )
        groups[key].append(payload)

    for key, values in sorted(groups.items()):
        successful = [value for value in values if value.get("status") == "ok"]
        print(" ".join((*key[:3], f"conflict={key[3]}")))
        if not successful:
            print("  no successful runs")
            continue
        for field in (
            "cpu_total_s",
            "peak_rss_kib",
            "outer_wall_s",
        ):
            samples = [float(value[field]) for value in successful]
            print(
                f"  {field}: median={statistics.median(samples):.6f} "
                f"min={min(samples):.6f} max={max(samples):.6f}"
            )
        child_rows = [value["child"] for value in successful]
        for field in ("wall_s", "spill_peak_bytes", "received_bytes"):
            samples = [float(value.get(field, 0)) for value in child_rows]
            print(
                f"  {field}: median={statistics.median(samples):.6f} "
                f"min={min(samples):.6f} max={max(samples):.6f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
