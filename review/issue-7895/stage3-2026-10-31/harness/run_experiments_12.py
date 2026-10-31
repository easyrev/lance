#!/usr/bin/env python3
"""Run Experiments 1 and 2 with interleaved builds."""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/mnt/lance/9617-bench")
FIXTURE = ROOT / "fixtures" / "experiment1-4m"
PARENT = ROOT / "bin" / "bench_parent.py"
PLAN_PARSER = ROOT / "bin" / "plan_parser.py"
BUILDS = ("U", "P1", "P2")
FORMATS = ("lance", "parquet")
SIZES = (1, 4, 16)


def write_spec(size: int, source_format: str) -> Path:
    metadata = json.loads((FIXTURE / "fixture.json").read_text())
    source_rows = int(metadata["sources"][str(size)]["rows"])
    expected_rows = int(
        metadata["sources"][str(size)]["expected_rows_after"]
    )
    spec = {
        "target_uri": str(FIXTURE / "target.lance"),
        "source_uri": str(FIXTURE / f"source-{size}gib.{source_format}"),
        "source_format": source_format,
        "base_rows": int(metadata["target_rows"]),
        "source_rows": source_rows,
        "expected_rows_after": expected_rows,
        "conflict_id": 0,
        "samples": [
            {
                "id": identifier,
                "columns": [
                    {"name": name, "value": value}
                    for name, value in expected_row.items()
                ],
            }
            for identifier, expected_row in (
                (int(key), value)
                for key, value in json.loads(
                    (FIXTURE / "expected-samples.json").read_text()
                ).items()
            )
        ],
        "experiment": "experiment1-2",
        "case": f"{size}gib-{source_format}",
        "storage": "local",
        "write_mode": "auto",
    }
    path = ROOT / "fixtures" / "specs" / f"exp1-{size}gib-{source_format}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return path


def run_parent(arguments: list[str]) -> dict:
    command = [str(PARENT), *arguments]
    completed = subprocess.run(command, text=True, capture_output=True)
    output = completed.stdout.strip().splitlines()
    payload: dict = {}
    for line in reversed(output):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            payload = value
            break
    if completed.returncode != 0:
        raise RuntimeError(
            f"cell failed: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return payload


def analyze_cell(
    spec: Path,
    size: int,
    source_rows: int,
    target_rows: int,
) -> None:
    for build in BUILDS:
        tag = f"exp1-analyze-{size}gib-{spec.stem.split('-')[-1]}-{build}"
        run_parent(
            [
                "--build",
                build,
                "--spec",
                str(spec),
                "--run-number",
                "0",
                "--analyze",
                "--tag",
                tag,
            ]
        )
        plan = ROOT / "plans" / f"{tag}.txt"
        parsed = subprocess.run(
            [str(PLAN_PARSER), str(plan), str(source_rows), str(target_rows)],
            text=True,
            capture_output=True,
            check=True,
        )
        result_path = ROOT / "results" / f"{tag}.plan.json"
        result_path.write_text(parsed.stdout)


def summarize() -> None:
    groups: dict[tuple, list[dict]] = {}
    for path in sorted(
        list((ROOT / "results").glob("exp1-run-*.json"))
        + list((ROOT / "results").glob("exp2-run-*.json"))
    ):
        outer = json.loads(path.read_text())
        if outer.get("status") != "ok":
            continue
        child = outer["child"]
        key = (
            child["experiment"],
            child["case"],
            child["build"],
            bool(child["conflict"]),
        )
        groups.setdefault(key, []).append(outer)
    rows = []
    for key, values in sorted(groups.items()):
        record = {"key": key, "runs": len(values)}
        for name, getter in (
            ("wall_s", lambda item: item["child"]["wall_s"]),
            ("cpu_total_s", lambda item: item["cpu_total_s"]),
            ("peak_rss_bytes", lambda item: item["peak_rss_kib"] * 1024),
            ("spill_peak_bytes", lambda item: item["child"]["spill_peak_bytes"]),
        ):
            samples = [float(getter(item)) for item in values]
            record[name] = {
                "median": statistics.median(samples),
                "min": min(samples),
                "max": max(samples),
                "spread_pct": (
                    (max(samples) - min(samples)) / statistics.median(samples) * 100
                    if statistics.median(samples)
                    else 0
                ),
            }
        rows.append(record)
    (ROOT / "results" / "experiments-1-2-summary.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n"
    )


def main() -> int:
    started = time.time()
    metadata = json.loads((FIXTURE / "fixture.json").read_text())
    target_rows = int(metadata["target_rows"])
    specs = {
        (size, source_format): write_spec(size, source_format)
        for size in SIZES
        for source_format in FORMATS
    }

    print("running Exp1 analyze plans", flush=True)
    for size in SIZES:
        source_rows = int(metadata["sources"][str(size)]["rows"])
        for source_format in FORMATS:
            analyze_cell(
                specs[(size, source_format)],
                size,
                source_rows,
                target_rows,
            )

    cell_index = 0
    for run_number in range(1, 6):
        for size in SIZES:
            runs = 3 if size == 16 else 5
            if run_number > runs:
                continue
            for source_format in FORMATS:
                rotate = (cell_index + run_number) % len(BUILDS)
                order = BUILDS[rotate:] + BUILDS[:rotate]
                for build in order:
                    tag = (
                        f"exp1-run-{size}gib-{source_format}-{build}-"
                        f"r{run_number}"
                    )
                    print(f"starting {tag}", flush=True)
                    run_parent(
                        [
                            "--build",
                            build,
                            "--spec",
                            str(specs[(size, source_format)]),
                            "--run-number",
                            str(run_number),
                            "--tag",
                            tag,
                        ]
                    )
                cell_index += 1
        summarize()

    print("running Exp2 one-conflict cells", flush=True)
    for run_number in range(1, 4):
        for size in (4, 16):
            for source_format in FORMATS:
                rotate = (cell_index + run_number) % len(BUILDS)
                order = BUILDS[rotate:] + BUILDS[:rotate]
                for build in order:
                    tag = (
                        f"exp2-run-{size}gib-{source_format}-{build}-"
                        f"r{run_number}"
                    )
                    print(f"starting {tag}", flush=True)
                    run_parent(
                        [
                            "--build",
                            build,
                            "--spec",
                            str(specs[(size, source_format)]),
                            "--run-number",
                            str(run_number),
                            "--conflict",
                            "--tag",
                            tag,
                        ]
                    )
                cell_index += 1
        summarize()

    summarize()
    print(
        json.dumps(
            {
                "status": "complete",
                "elapsed_s": time.time() - started,
                "summary": str(ROOT / "results" / "experiments-1-2-summary.json"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
