#!/usr/bin/env python3
"""Run the required 4 GiB Parquet and Lance cold-cache subset."""

from __future__ import annotations

import json
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path("/mnt/lance/9617-bench")
PARENT = ROOT / "bin" / "bench_parent.py"
BUILDS = ("U", "P1", "P2")


def drop_caches() -> None:
    subprocess.run(["sync"], check=True)
    with open("/proc/sys/vm/drop_caches", "w", encoding="ascii") as handle:
        handle.write("3\n")


def run_parent(arguments: list[str]) -> dict:
    completed = subprocess.run(
        [str(PARENT), *arguments],
        text=True,
        capture_output=True,
    )
    payload: dict = {}
    for line in reversed(completed.stdout.strip().splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stdout + "\n" + completed.stderr
        )
    return payload


def main() -> int:
    started = time.time()
    for run_number in range(1, 4):
        for source_format in ("lance", "parquet"):
            spec = (
                ROOT
                / "fixtures"
                / "specs"
                / f"exp1-4gib-{source_format}.json"
            )
            rotate = run_number % len(BUILDS)
            order = BUILDS[rotate:] + BUILDS[:rotate]
            for build in order:
                drop_caches()
                tag = (
                    f"cold-run-4gib-{source_format}-{build}-r{run_number}"
                )
                print(f"starting {tag}", flush=True)
                run_parent(
                    [
                        "--build",
                        build,
                        "--spec",
                        str(spec),
                        "--run-number",
                        str(run_number),
                        "--tag",
                        tag,
                    ]
                )

    groups: dict[tuple, list[dict]] = {}
    for path in (ROOT / "results").glob("cold-run-*.json"):
        outer = json.loads(path.read_text())
        child = outer["child"]
        key = (child["case"], child["build"])
        groups.setdefault(key, []).append(outer)
    output = []
    for key, values in sorted(groups.items()):
        record = {
            "case": key[0],
            "build": key[1],
            "runs": len(values),
        }
        for name, getter in (
            ("wall_s", lambda value: value["child"]["wall_s"]),
            ("cpu_total_s", lambda value: value["cpu_total_s"]),
            (
                "peak_rss_bytes",
                lambda value: value["peak_rss_kib"] * 1024,
            ),
            (
                "spill_peak_bytes",
                lambda value: value["child"]["spill_peak_bytes"],
            ),
        ):
            samples = [float(getter(value)) for value in values]
            median = statistics.median(samples)
            record[name] = {
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
    (ROOT / "results" / "cold-cache-summary.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "status": "complete",
                "elapsed_s": time.time() - started,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
