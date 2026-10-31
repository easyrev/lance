#!/usr/bin/env python3
"""Restore a benchmark target to its tagged base version."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def load_worker():
    path = Path(__file__).with_name("bench_worker.py")
    spec = importlib.util.spec_from_file_location("bench_worker", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_worker"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args()
    worker = load_worker()
    spec = json.loads(args.spec.read_text())
    worker.reset_to_base(
        worker.dataset_uri(spec, "target_uri"),
        spec,
        int(spec["base_rows"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
