#!/usr/bin/env python3
"""Run the constrained-temp Experiment 5 cells on the 4 GiB loop device."""

from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path("/mnt/lance/9617-bench")
LOCKED_TMP = ROOT / "loop-tmp"
PARENT = ROOT / "bin" / "bench_parent.py"
FIXTURE = ROOT / "fixtures" / "experiment1-4m"


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
    payload["_returncode"] = completed.returncode
    payload["_stderr"] = completed.stderr
    return payload


def main() -> int:
    metadata = json.loads((FIXTURE / "fixture.json").read_text())
    expected = json.loads((FIXTURE / "expected-samples.json").read_text())
    specs = {}
    for size in (1, 4, 16):
        spec = {
            "target_uri": str(FIXTURE / "target.lance"),
            "source_uri": str(FIXTURE / f"source-{size}gib.lance"),
            "source_format": "lance",
            "base_rows": int(metadata["target_rows"]),
            "source_rows": int(metadata["sources"][str(size)]["rows"]),
            "expected_rows_after": int(
                metadata["sources"][str(size)]["expected_rows_after"]
            ),
            "conflict_id": 0,
            "samples": [
                {
                    "id": int(identifier),
                    "columns": [
                        {"name": name, "value": value}
                        for name, value in row.items()
                    ],
                }
                for identifier, row in expected.items()
            ],
            "experiment": "experiment5",
            "case": f"{size}gib-lance",
            "storage": "local",
            "write_mode": "auto",
        }
        path = ROOT / "fixtures" / "specs" / f"exp5-{size}gib.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
        specs[size] = path

    started = time.time()
    for run_number in range(1, 4):
        for size in (1, 4, 16):
            builds = ("U", "P2") if run_number % 2 else ("P2", "U")
            for build in builds:
                tag = f"exp5-run-{size}gib-{build}-r{run_number}"
                print(f"starting {tag}", flush=True)
                result = run_parent(
                    [
                        "--build",
                        build,
                        "--spec",
                        str(specs[size]),
                        "--run-number",
                        str(run_number),
                        "--tmp-root",
                        str(LOCKED_TMP),
                        "--tag",
                        tag,
                    ]
                )
                if result.get("status") != "ok":
                    print(
                        f"recorded failure {tag}: "
                        f"{result.get('child', {}).get('message', result)}",
                        flush=True,
                    )
                run_dir = LOCKED_TMP / tag
                if run_dir.exists():
                    shutil.rmtree(run_dir)

    groups: dict[tuple, list[dict]] = {}
    for path in (ROOT / "results").glob("exp5-run-*.json"):
        outer = json.loads(path.read_text())
        child = outer.get("child", {})
        key = (child.get("case"), child.get("build"))
        groups.setdefault(key, []).append(outer)
    output = []
    for key, values in sorted(groups.items(), key=str):
        successes = [value for value in values if value.get("status") == "ok"]
        record = {
            "case": key[0],
            "build": key[1],
            "attempts": len(values),
            "successes": len(successes),
            "failures": len(values) - len(successes),
        }
        spill = [
            float(value.get("child", {}).get("spill_peak_bytes", 0))
            for value in values
        ]
        record["spill_peak_bytes"] = {
            "median": statistics.median(spill),
            "min": min(spill),
            "max": max(spill),
        }
        if successes:
            wall = [float(value["child"]["wall_s"]) for value in successes]
            rss = [float(value["peak_rss_kib"] * 1024) for value in successes]
            record["wall_s"] = {
                "median": statistics.median(wall),
                "min": min(wall),
                "max": max(wall),
            }
            record["peak_rss_bytes"] = {
                "median": statistics.median(rss),
                "min": min(rss),
                "max": max(rss),
            }
        output.append(record)
    (ROOT / "results" / "experiment5-summary.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "status": "complete",
                "elapsed_s": time.time() - started,
                "summary": str(ROOT / "results" / "experiment5-summary.json"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
