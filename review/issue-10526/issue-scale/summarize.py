#!/usr/bin/env python3
"""Summarize the checks and measured trials without counting warmups."""
import csv
import statistics
import sys
from pathlib import Path

evidence = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
for status in sorted(evidence.glob("*.exit")):
    print(f"{status.stem}: exit {status.read_text().strip()}")
measurements = evidence / "measurements.tsv"
if not measurements.exists():
    sys.exit(0)

with measurements.open(newline="") as raw:
    rows = list(csv.DictReader(raw, delimiter="\t"))
if not rows:
    sys.exit(0)

assert len({row["input_fnv64"] for row in rows}) == 1
assert len({row["take_indices"] for row in rows}) == 1
for build in ("base", "final"):
    trials = [row for row in rows if row["build"] == build]
    print(f"\n{build} (n={len(trials)})")
    if not trials:
        continue
    for name in ("file_bytes", "pages", "max_raw_bytes", "max_encoded_bytes"):
        print(f"  {name}: {', '.join(sorted({row[name] for row in trials}))}")
    for name in ("write_s", "write_cpu_s", "write_avg_cores", "scan_s", "take_s"):
        values = [float(row[name]) for row in trials]
        print(f"  {name}: median {statistics.median(values):.6f}, range {min(values):.6f}–{max(values):.6f}")
