#!/usr/bin/env python3
"""Rerun conflict cells that reached the old artificial retry timeout."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path("/mnt/lance/9617-bench")
TAG_PATTERN = re.compile(
    r"^exp2-run-(?P<size>4|16)gib-(?P<format>lance|parquet)-"
    r"(?P<build>U|P1|P2)-r(?P<run>[1-3])$"
)


def load_runner():
    path = Path(__file__).with_name("run_experiments_12.py")
    spec = importlib.util.spec_from_file_location("stage3_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["stage3_runner"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    runner = load_runner()
    rerun = []
    for path in sorted((ROOT / "results").glob("exp2-run-*.json")):
        payload = json.loads(path.read_text())
        child = payload.get("child", {})
        if child.get("error_type") != "OSError":
            continue
        if "retry_timeout" not in child.get("message", ""):
            continue
        match = TAG_PATTERN.fullmatch(path.stem)
        if match is None:
            raise ValueError(f"cannot parse result tag: {path.stem}")
        rerun.append((path.stem, match.groupdict()))

    for tag, match in rerun:
        size = int(match["size"])
        source_format = match["format"]
        spec = runner.write_spec(size, source_format)
        print(f"rerunning timeout cell {tag}", flush=True)
        runner.run_parent(
            [
                "--build",
                match["build"],
                "--spec",
                str(spec),
                "--run-number",
                match["run"],
                "--conflict",
                "--tag",
                tag,
            ]
        )
    runner.summarize()
    print(
        json.dumps({"status": "complete", "rerun": len(rerun)}, sort_keys=True),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
