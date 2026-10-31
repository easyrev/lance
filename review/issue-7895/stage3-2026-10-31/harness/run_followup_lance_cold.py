#!/usr/bin/env python3
"""Measure P1 and P2 on the 16 GiB source with cold page cache."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path("/mnt/lance/9617-bench")
PARENT = ROOT / "bin" / "bench_parent.py"
SPEC = ROOT / "fixtures" / "specs" / "followup-16gib-lance.json"


def drop_caches() -> None:
    subprocess.run(["sync"], check=True)
    with open("/proc/sys/vm/drop_caches", "w", encoding="ascii") as handle:
        handle.write("3\n")


def main() -> int:
    for run_number in range(1, 4):
        builds = ("P1", "P2") if run_number % 2 else ("P2", "P1")
        for build in builds:
            drop_caches()
            tag = f"followup-cold-16gib-{build}-r{run_number}"
            print(f"starting {tag}", flush=True)
            result = subprocess.run(
                [
                    str(PARENT),
                    "--build",
                    build,
                    "--spec",
                    str(SPEC),
                    "--run-number",
                    str(run_number),
                    "--tag",
                    tag,
                ],
                text=True,
                capture_output=True,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stdout + "\n" + result.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
