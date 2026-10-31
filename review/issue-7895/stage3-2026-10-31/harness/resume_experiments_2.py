#!/usr/bin/env python3
"""Resume missing Experiment 2 cells after the retry-timeout fix."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path("/mnt/lance/9617-bench")


def load_runner():
    path = Path(__file__).with_name("run_experiments_12.py")
    spec = importlib.util.spec_from_file_location("stage3_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["stage3_runner"] = module
    spec.loader.exec_module(module)
    return module


def completed(tag: str) -> bool:
    path = ROOT / "results" / f"{tag}.json"
    return path.exists()


def main() -> int:
    runner = load_runner()
    started = time.time()
    count = 0
    for run_number in range(1, 4):
        for size in (4, 16):
            for source_format in runner.FORMATS:
                spec_path = runner.write_spec(size, source_format)
                rotate = (size + run_number) % len(runner.BUILDS)
                order = (
                    runner.BUILDS[rotate:] + runner.BUILDS[:rotate]
                )
                for build in order:
                    tag = (
                        f"exp2-run-{size}gib-{source_format}-{build}-"
                        f"r{run_number}"
                    )
                    if completed(tag):
                        print(f"skip complete {tag}", flush=True)
                        continue
                    print(f"starting {tag}", flush=True)
                    try:
                        runner.run_parent(
                            [
                                "--build",
                                build,
                                "--spec",
                                str(spec_path),
                                "--run-number",
                                str(run_number),
                                "--conflict",
                                "--tag",
                                tag,
                            ]
                        )
                    except RuntimeError as exc:
                        print(f"recorded failure {tag}: {exc}", flush=True)
                    count += 1
    runner.summarize()
    print(
        json.dumps(
            {
                "status": "complete",
                "new_runs": count,
                "elapsed_s": time.time() - started,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
