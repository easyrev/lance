#!/usr/bin/env python3
"""Compare current Parquet scanner settings with two local variants."""

from __future__ import annotations

import json
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path("/mnt/lance/9617-bench")
FIXTURE = ROOT / "fixtures" / "experiment1-4m"
PARENT = ROOT / "bin" / "bench_parent.py"


def make_spec(size: int, variant: str) -> Path:
    metadata = json.loads((FIXTURE / "fixture.json").read_text())
    expected = json.loads((FIXTURE / "expected-samples.json").read_text())
    spec = {
        "target_uri": str(FIXTURE / "target.lance"),
        "source_uri": str(FIXTURE / f"source-{size}gib.parquet"),
        "source_format": "parquet",
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
        "experiment": "parquet-variants",
        "case": f"{size}gib-parquet",
        "storage": "local",
        "write_mode": "auto",
        "parquet_adapter_variant": variant,
    }
    path = (
        ROOT
        / "fixtures"
        / "specs"
        / f"parquet-{variant}-{size}gib.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return path


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
        payload.setdefault("status", "error")
        payload["message"] = completed.stdout + completed.stderr
    return payload


def metrics(values: list[dict]) -> dict:
    successes = [value for value in values if value.get("status") == "ok"]
    result = {
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
    ):
        samples = [float(getter(value)) for value in successes]
        if not samples:
            continue
        median = statistics.median(samples)
        result[name] = {
            "median": median,
            "min": min(samples),
            "max": max(samples),
            "spread_pct": (
                (max(samples) - min(samples)) / median * 100
                if median
                else 0
            ),
        }
    return result


def load(paths: list[Path]) -> list[dict]:
    return [json.loads(path.read_text()) for path in paths]


def main() -> int:
    started = time.time()
    specs = {
        (size, variant): make_spec(size, variant)
        for size in (4, 16)
        for variant in ("readahead_1", "byte_budget")
    }
    for run_number in range(1, 4):
        for conflict in (False, True):
            for size in (4, 16):
                variants = (
                    ("readahead_1", "byte_budget")
                    if run_number % 2
                    else ("byte_budget", "readahead_1")
                )
                for variant in variants:
                    tag = (
                        f"expv-{variant}-{size}gib-"
                        f"{'conflict' if conflict else 'no-conflict'}-"
                        f"r{run_number}"
                    )
                    print(f"starting {tag}", flush=True)
                    payload = run_parent(
                        [
                            "--build",
                            "P2",
                            "--spec",
                            str(specs[(size, variant)]),
                            "--run-number",
                            str(run_number),
                            *(["--conflict"] if conflict else []),
                            "--tag",
                            tag,
                        ]
                    )
                    if payload.get("status") != "ok":
                        print(
                            f"recorded failure {tag}: "
                            f"{payload.get('child', {}).get('message', payload)}",
                            flush=True,
                        )

    comparison = []
    for size in (4, 16):
        for conflict in (False, True):
            prefix = "exp2" if conflict else "exp1"
            current = load(
                sorted(
                    (ROOT / "results").glob(
                        f"{prefix}-run-{size}gib-parquet-P2-r*.json"
                    )
                )
            )
            u_values = load(
                sorted(
                    (ROOT / "results").glob(
                        f"{prefix}-run-{size}gib-parquet-U-r*.json"
                    )
                )
            )
            row = {
                "size_gib": size,
                "conflict": conflict,
                "current": metrics(current),
                "U": metrics(u_values),
            }
            for variant in ("readahead_1", "byte_budget"):
                values = load(
                    sorted(
                        (ROOT / "results").glob(
                            f"expv-{variant}-{size}gib-"
                            f"{'conflict' if conflict else 'no-conflict'}-r*.json"
                        )
                    )
                )
                row[variant] = metrics(values)
            current_metrics = row["current"]
            u_metrics = row["U"]
            for variant in ("readahead_1", "byte_budget"):
                candidate = row[variant]
                if not candidate.get("successes"):
                    row[f"{variant}_qualifies"] = False
                    continue
                rss_ok = (
                    candidate["peak_rss_bytes"]["median"]
                    <= u_metrics["peak_rss_bytes"]["median"]
                )
                wall_ok = (
                    candidate["wall_s"]["median"]
                    <= current_metrics["wall_s"]["median"] * 1.05
                )
                cpu_ok = (
                    candidate["cpu_total_s"]["median"]
                    <= current_metrics["cpu_total_s"]["median"] * 1.05
                )
                row[f"{variant}_qualifies"] = rss_ok and wall_ok and cpu_ok
                row[f"{variant}_checks"] = {
                    "rss_ok": rss_ok,
                    "wall_ok": wall_ok,
                    "cpu_ok": cpu_ok,
                }
            comparison.append(row)

    selected = "current"
    for variant in ("readahead_1", "byte_budget"):
        if all(row[f"{variant}_qualifies"] for row in comparison):
            selected = variant
            break
    result = {
        "status": "complete",
        "selected": selected,
        "comparison": comparison,
        "elapsed_s": time.time() - started,
    }
    (ROOT / "results" / "parquet-variants-summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"status": "complete", "selected": selected}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
