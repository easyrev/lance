#!/usr/bin/env python3
"""Generate and run Experiment 3 one target size at a time."""

from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path("/mnt/lance/9617-bench")
PARENT = ROOT / "bin" / "bench_parent.py"
PLAN_PARSER = ROOT / "bin" / "plan_parser.py"
MAKE_FIXTURE = ROOT / "bin" / "make_pilot_fixture.py"
RESET_TARGET = ROOT / "bin" / "reset_target.py"
PYTHON = Path("/mnt/lance/9617-preflight/venv/P2/bin/python")
SIZES = (1_000_000, 4_000_000, 8_000_000, 16_000_000)


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
        raise RuntimeError(
            f"cell failed: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return payload


def make_fixture(rows: int) -> Path:
    root = ROOT / "fixtures" / f"exp3-{rows}"
    subprocess.run(
        [
            str(PYTHON),
            str(MAKE_FIXTURE),
            "--root",
            str(root),
            "--kind",
            "wide",
            "--target-rows",
            str(rows),
            "--partial-source-rows",
            "100000",
        ],
        check=True,
    )
    return root


def make_spec(root: Path, rows: int) -> Path:
    fixture = json.loads((root / "fixture.json").read_text())
    expected = json.loads((root / "expected-samples.json").read_text())
    samples = [
        {
            "id": int(identifier),
            "columns": [
                {"name": name, "value": value}
                for name, value in row.items()
            ],
        }
        for identifier, row in expected.items()
    ]
    spec = {
        "target_uri": str(root / "target.lance"),
        "source_uri": str(root / "source.lance"),
        "source_format": "lance",
        "base_rows": rows,
        "source_rows": int(fixture["source_rows"]),
        "expected_rows_after": rows,
        "conflict_id": 0,
        "samples": samples,
        "experiment": "experiment3",
        "case": f"{rows}rows-wide",
        "storage": "local",
        "write_mode": "auto",
    }
    path = ROOT / "fixtures" / "specs" / f"exp3-{rows}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return path


def analyze(spec: Path, rows: int, source_rows: int, builds: list[str]) -> None:
    for build in builds:
        tag = f"exp3-analyze-{rows}-{build}"
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
        parsed = subprocess.run(
            [
                str(PLAN_PARSER),
                str(ROOT / "plans" / f"{tag}.txt"),
                str(source_rows),
                str(rows),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        (ROOT / "results" / f"{tag}.plan.json").write_text(parsed.stdout)


def run_cell(
    build: str,
    spec: Path,
    rows: int,
    run_number: int,
    *,
    memory_cap_gib: int | None = None,
) -> bool:
    prefix = "exp3-cap" if memory_cap_gib else "exp3-run"
    tag = f"{prefix}-{rows}-{build}-r{run_number}"
    command = [
        "--build",
        build,
        "--spec",
        str(spec),
        "--run-number",
        str(run_number),
        "--tag",
        tag,
    ]
    if memory_cap_gib:
        command.extend(["--memory-cap-gib", str(memory_cap_gib)])
    print(f"starting {tag}", flush=True)
    try:
        run_parent(command)
        return True
    except RuntimeError as exc:
        print(f"recorded failure {tag}: {exc}", flush=True)
        subprocess.run(
            [str(PYTHON), str(RESET_TARGET), "--spec", str(spec)],
            check=True,
        )
        return False


def summarize() -> None:
    groups: dict[tuple, list[dict]] = {}
    for prefix in ("exp3-run", "exp3-cap"):
        for path in (ROOT / "results").glob(f"{prefix}-*.json"):
            outer = json.loads(path.read_text())
            child = outer.get("child", {})
            key = (
                prefix,
                child.get("case"),
                child.get("build"),
                outer.get("memory_cap_gib"),
            )
            groups.setdefault(key, []).append(outer)
    output = []
    for key, values in sorted(groups.items(), key=str):
        successes = [value for value in values if value.get("status") == "ok"]
        record: dict = {
            "kind": key[0],
            "case": key[1],
            "build": key[2],
            "memory_cap_gib": key[3],
            "attempts": len(values),
            "successes": len(successes),
            "failures": len(values) - len(successes),
        }
        for name, getter in (
            ("wall_s", lambda value: value["child"]["wall_s"]),
            ("cpu_total_s", lambda value: value["cpu_total_s"]),
            (
                "peak_rss_bytes",
                lambda value: value["peak_rss_kib"] * 1024,
            ),
        ):
            samples = [float(getter(value)) for value in successes]
            if samples:
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
    (ROOT / "results" / "experiment3-summary.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )


def main() -> int:
    started = time.time()
    p1_cap_oom_rows: int | None = None
    for rows in SIZES:
        fixture_root = make_fixture(rows)
        spec = make_spec(fixture_root, rows)
        source_rows = int(
            json.loads((fixture_root / "fixture.json").read_text())[
                "source_rows"
            ]
        )
        normal_builds = ["U", "P1", "P2"] if rows <= 4_000_000 else ["P1", "P2"]
        analyze(spec, rows, source_rows, normal_builds)
        for run_number in range(1, 4):
            rotate = (SIZES.index(rows) + run_number) % len(normal_builds)
            order = normal_builds[rotate:] + normal_builds[:rotate]
            for build in order:
                run_cell(build, spec, rows, run_number)

        if p1_cap_oom_rows is None:
            for run_number in range(1, 4):
                run_cell(
                    "P1",
                    spec,
                    rows,
                    run_number,
                    memory_cap_gib=16,
                )
            p1_results = [
                json.loads(path.read_text())
                for path in (ROOT / "results").glob(
                    f"exp3-cap-{rows}-P1-r*.json"
                )
            ]
            if any(value.get("status") != "ok" for value in p1_results):
                p1_cap_oom_rows = rows
                for run_number in range(1, 4):
                    run_cell(
                        "P2",
                        spec,
                        rows,
                        run_number,
                        memory_cap_gib=16,
                    )
            else:
                for run_number in range(1, 4):
                    run_cell(
                        "P2",
                        spec,
                        rows,
                        run_number,
                        memory_cap_gib=16,
                    )

        summarize()
        shutil.rmtree(fixture_root)
        print(f"deleted fixture {fixture_root}", flush=True)

    summarize()
    print(
        json.dumps(
            {
                "status": "complete",
                "p1_first_oom_rows": p1_cap_oom_rows,
                "elapsed_s": time.time() - started,
                "summary": str(ROOT / "results" / "experiment3-summary.json"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
