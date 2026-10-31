#!/usr/bin/env python3
"""Resume the 16M rows-wide cells from an existing Experiment 3 fixture."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/mnt/lance/9617-bench")
ROWS = 16_000_000


def load_runner():
    path = Path(__file__).with_name("run_experiment3.py")
    spec = importlib.util.spec_from_file_location("stage3_exp3", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["stage3_exp3"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    runner = load_runner()
    fixture = ROOT / "fixtures" / "exp3-16000000"
    metadata = json.loads((fixture / "fixture.json").read_text())
    if int(metadata["target_rows"]) != ROWS:
        raise ValueError("fixture row count does not match resume target")
    spec = runner.make_spec(fixture, ROWS)
    source_rows = int(metadata["source_rows"])
    subprocess.run(
        [str(runner.PYTHON), str(runner.RESET_TARGET), "--spec", str(spec)],
        check=True,
    )
    runner.analyze(spec, ROWS, source_rows, ["P2"])
    p1_tag = f"exp3-analyze-{ROWS}-P1"
    try:
        runner.run_parent(
            [
                "--build",
                "P1",
                "--spec",
                str(spec),
                "--run-number",
                "0",
                "--analyze",
                "--memory-cap-gib",
                "56",
                "--tag",
                p1_tag,
            ]
        )
        parsed = subprocess.run(
            [
                str(runner.PLAN_PARSER),
                str(ROOT / "plans" / f"{p1_tag}.txt"),
                str(source_rows),
                str(ROWS),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        (ROOT / "results" / f"{p1_tag}.plan.json").write_text(parsed.stdout)
    except RuntimeError as exc:
        (ROOT / "results" / f"{p1_tag}.plan-error.json").write_text(
            json.dumps({"status": "error", "message": str(exc)}) + "\n"
        )
        subprocess.run(
            [str(runner.PYTHON), str(runner.RESET_TARGET), "--spec", str(spec)],
            check=True,
        )
    for run_number in range(1, 4):
        order = ["P2", "P1"] if run_number % 2 else ["P1", "P2"]
        for build in order:
            if build == "P2":
                runner.run_cell(build, spec, ROWS, run_number)
                continue
            tag = f"exp3-run-{ROWS}-P1-r{run_number}"
            print(f"starting {tag} with 56 GiB safety cap", flush=True)
            try:
                runner.run_parent(
                    [
                        "--build",
                        "P1",
                        "--spec",
                        str(spec),
                        "--run-number",
                        str(run_number),
                        "--memory-cap-gib",
                        "56",
                        "--tag",
                        tag,
                    ]
                )
            except RuntimeError as exc:
                print(f"recorded failure {tag}: {exc}", flush=True)
                subprocess.run(
                    [
                        str(runner.PYTHON),
                        str(runner.RESET_TARGET),
                        "--spec",
                        str(spec),
                    ],
                    check=True,
                )
        runner.summarize()
    shutil.rmtree(fixture)
    runner.summarize()
    print(
        json.dumps(
            {
                "status": "complete",
                "summary": str(ROOT / "results" / "experiment3-summary.json"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
