#!/usr/bin/env python3
"""Run Experiment 4 against the verified OSS datasets."""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

from bench_worker import load_oss_env

ROOT = Path("/mnt/lance/9617-bench")
FIXTURE = ROOT / "fixtures" / "experiment1-4m"
PARENT = ROOT / "bin" / "bench_parent.py"


def run_parent(arguments: list[str]) -> dict:
    command = [str(PARENT), *arguments]
    completed = subprocess.run(command, text=True, capture_output=True)
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
        return {
            "status": "error",
            "message": completed.stdout + completed.stderr,
        }
    return payload


def make_spec(bucket: str, prefix: str, source_format: str) -> Path:
    metadata = json.loads((FIXTURE / "fixture.json").read_text())
    source_rows = int(metadata["sources"]["4"]["rows"])
    expected_rows = int(
        metadata["sources"]["4"]["expected_rows_after"]
    )
    expected = json.loads((FIXTURE / "expected-samples.json").read_text())
    spec = {
        "target_uri": f"oss://{bucket}/{prefix}/exp4/target.lance",
        "source_uri": (
            f"oss://{bucket}/{prefix}/exp4/source-4gib.{source_format}"
        ),
        "source_format": source_format,
        "base_rows": int(metadata["target_rows"]),
        "source_rows": source_rows,
        "expected_rows_after": expected_rows,
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
        "experiment": "experiment4",
        "case": f"oss-4gib-{source_format}",
        "storage": "oss",
        "write_mode": "auto",
    }
    path = ROOT / "fixtures" / "specs" / f"exp4-{source_format}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return path


def summarize() -> None:
    groups: dict[tuple, list[dict]] = {}
    for path in (ROOT / "results").glob("exp4-run-*.json"):
        outer = json.loads(path.read_text())
        child = outer.get("child", {})
        key = (
            child.get("case"),
            child.get("build"),
            bool(child.get("conflict")),
        )
        groups.setdefault(key, []).append(outer)
    output = []
    for key, values in sorted(groups.items(), key=str):
        successes = [value for value in values if value.get("status") == "ok"]
        record = {
            "case": key[0],
            "build": key[1],
            "conflict": key[2],
            "attempts": len(values),
            "successes": len(successes),
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
            (
                "received_bytes",
                lambda value: value["child"]["received_bytes"],
            ),
        ):
            samples = [float(getter(value)) for value in successes]
            if not samples:
                continue
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
    (ROOT / "results" / "experiment4-summary.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )


def cleanup(bucket: str, prefix: str) -> None:
    import oss_setup

    filesystem = oss_setup.make_filesystem()
    count = oss_setup.delete_prefix(filesystem, bucket, prefix)
    (ROOT / "state" / "oss-cleanup.json").write_text(
        json.dumps({"deleted_objects": count}, sort_keys=True) + "\n"
    )


def main() -> int:
    load_oss_env()
    bucket = os.environ["OSS_BUCKET"]
    prefix = os.environ.get("LANCE_9617_PREFIX", "_stage3_9617")
    specs = {
        source_format: make_spec(bucket, prefix, source_format)
        for source_format in ("lance", "parquet")
    }
    started = time.time()
    cell = 0
    for conflict in (False, True):
        for run_number in range(1, 4):
            for source_format in ("lance", "parquet"):
                rotate = (cell + run_number) % 2
                builds = ("U", "P2")[rotate:] + ("U", "P2")[:rotate]
                for build in builds:
                    tag = (
                        f"exp4-run-{source_format}-"
                        f"{'conflict' if conflict else 'no-conflict'}-"
                        f"{build}-r{run_number}"
                    )
                    print(f"starting {tag}", flush=True)
                    result = run_parent(
                        [
                            "--build",
                            build,
                            "--spec",
                            str(specs[source_format]),
                            "--run-number",
                            str(run_number),
                            "--oss",
                            *(["--conflict"] if conflict else []),
                            "--tag",
                            tag,
                        ]
                    )
                    if result.get("status") != "ok":
                        print(
                            f"recorded failure {tag}: "
                            f"{result.get('message', result)}",
                            flush=True,
                        )
                cell += 1
            summarize()
    summarize()
    cleanup(bucket, prefix)
    print(
        json.dumps(
            {
                "status": "complete",
                "elapsed_s": time.time() - started,
                "summary": str(ROOT / "results" / "experiment4-summary.json"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
