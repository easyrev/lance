#!/usr/bin/env python3
"""Measure P1 and P2 on the 16 GiB Lance source with disk counters."""

from __future__ import annotations

import json
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path("/mnt/lance/9617-bench")
PARENT = ROOT / "bin" / "bench_parent.py"
SPEC = ROOT / "fixtures" / "specs" / "followup-16gib-lance.json"
GIB = 1024**3


def run_parent(arguments: list[str]) -> dict:
    completed = subprocess.run(
        [str(PARENT), *arguments],
        text=True,
        capture_output=True,
    )
    payload: dict = {}
    for line in reversed(completed.stdout.strip().splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            payload = value
            break
    if completed.returncode != 0:
        raise RuntimeError(completed.stdout + "\n" + completed.stderr)
    return payload


def summarize() -> None:
    groups: dict[str, list[dict]] = {}
    for path in (ROOT / "results").glob("followup-lance-16gib-*.json"):
        data = json.loads(path.read_text())
        groups.setdefault(data["child"]["build"], []).append(data)
    output = []
    for build, values in sorted(groups.items()):
        record = {"build": build, "runs": len(values)}
        for field, getter in (
            ("wall_s", lambda value: value["child"]["wall_s"]),
            ("cpu_total_s", lambda value: value["cpu_total_s"]),
            (
                "peak_rss_bytes",
                lambda value: value["peak_rss_kib"] * 1024,
            ),
            (
                "read_mib_s",
                lambda value: value["child"]["disk_read_bytes"]
                / GIB
                / value["child"]["wall_s"],
            ),
            (
                "disk_read_bytes",
                lambda value: value["child"]["disk_read_bytes"],
            ),
            ("disk_read_ms", lambda value: value["child"]["disk_read_ms"]),
        ):
            samples = [float(getter(value)) for value in values]
            median = statistics.median(samples)
            record[field] = {
                "median": median,
                "min": min(samples),
                "max": max(samples),
                "spread_pct": (
                    (max(samples) - min(samples)) / median * 100
                    if median
                    else 0
                ),
            }
        output.append(record)
    (ROOT / "results" / "followup-lance-summary.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )


def main() -> int:
    started = time.time()
    for run_number in range(1, 4):
        builds = ("P1", "P2") if run_number % 2 else ("P2", "P1")
        for build in builds:
            tag = f"followup-lance-16gib-{build}-r{run_number}"
            print(f"starting {tag}", flush=True)
            run_parent(
                [
                    "--build",
                    build,
                    "--spec",
                    str(SPEC),
                    "--run-number",
                    str(run_number),
                    "--tag",
                    tag,
                ]
            )
        summarize()
    print(
        json.dumps(
            {
                "status": "complete",
                "elapsed_s": time.time() - started,
                "summary": str(
                    ROOT / "results" / "followup-lance-summary.json"
                ),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
