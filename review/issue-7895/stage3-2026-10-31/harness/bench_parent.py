#!/usr/bin/env python3
"""Start one benchmark child, account with wait4, and store raw JSON."""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path("/mnt/lance/9617-bench")
VENVS = Path("/mnt/lance/9617-preflight/venv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build",
        choices=("U", "P1", "P2", "P2B"),
        required=True,
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--run-number", type=int, required=True)
    parser.add_argument("--conflict", action="store_true")
    parser.add_argument("--oss", action="store_true")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--tmp-root", type=Path, default=ROOT / "tmp")
    parser.add_argument("--memory-cap-gib", type=int)
    parser.add_argument("--tag", required=True)
    return parser.parse_args()


def wait4_collect(pid: int) -> tuple[int, resource.struct_rusage]:
    while True:
        waited_pid, status, usage = os.wait4(pid, 0)
        if waited_pid == pid:
            return status, usage


def main() -> int:
    args = parse_args()
    run_root = args.tmp_root / args.tag
    run_root.mkdir(parents=True, exist_ok=True)
    child_tmp = run_root / "spill"
    stdout_path = ROOT / "logs" / f"{args.tag}.stdout.log"
    stderr_path = ROOT / "logs" / f"{args.tag}.stderr.log"
    result_path = ROOT / "results" / f"{args.tag}.json"

    command = [
        str(
            (
                ROOT / "venv" / "P2-bounded"
                if args.build == "P2B"
                else VENVS / args.build
            )
            / "bin"
            / "python"
        ),
        str(ROOT / "bin" / "bench_worker.py"),
        "--build",
        args.build,
        "--spec",
        str(args.spec),
        "--run-number",
        str(args.run_number),
        "--tmpdir",
        str(child_tmp),
    ]
    if args.conflict:
        command.append("--conflict")
    if args.oss:
        command.append("--oss")
    if args.analyze:
        command.extend(
            [
                "--analyze",
                "--plan-out",
                str(ROOT / "plans" / f"{args.tag}.txt"),
            ]
        )
    if args.memory_cap_gib:
        command = [
            "systemd-run",
            "--scope",
            "-p",
            f"MemoryMax={args.memory_cap_gib}G",
            "-p",
            "MemorySwapMax=0",
            "--",
            *command,
        ]

    started = time.time()
    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        process = subprocess.Popen(command, stdout=stdout_file, stderr=stderr_file)
        status, usage = wait4_collect(process.pid)
    elapsed = time.time() - started
    exit_code = os.waitstatus_to_exitcode(status)
    if exit_code < 0:
        exit_code = 128 + (-exit_code)

    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
    lines = [line for line in stdout_text.splitlines() if line.strip()]
    child_result: dict[str, Any] = {}
    for line in reversed(lines):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            child_result = candidate
            break

    parent_result = {
        "status": child_result.get("status", "error"),
        "exit_code": exit_code,
        "outer_wall_s": elapsed,
        "cpu_user_s": usage.ru_utime,
        "cpu_system_s": usage.ru_stime,
        "cpu_total_s": usage.ru_utime + usage.ru_stime,
        "peak_rss_kib": usage.ru_maxrss,
        "page_faults": usage.ru_majflt,
        "child": child_result,
        "memory_cap_gib": args.memory_cap_gib,
        "tmp_root": str(args.tmp_root),
        "command": [part if part != str(ROOT / "bin" / "bench_worker.py") else "bench_worker.py" for part in command],
    }
    result_path.write_text(
        json.dumps(parent_result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(parent_result, sort_keys=True))
    return 0 if exit_code == 0 and child_result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
