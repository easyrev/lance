# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright The Lance Authors

"""Run a benchmark layer, one fresh measured process per run, upstream/PR alternating.

Stdlib only; runs under the system python3.  Each run:

  1. restore the target to its pristine tag (untimed, separate process)
  2. warm (read source + target files) or drop the page cache
  3. spawn run_merge.py with a fresh TMPDIR; poll TMPDIR usage and child RSS;
     reap it with wait4 for user/sys CPU and peak RSS
  4. verify row count, version count and sampled rows (untimed)
  5. append one line to results/raw.jsonl

    python3 driver.py --layer A --tiers 128m,1g --reps 5
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path("/mnt/lance/bench-9617")
HARNESS = ROOT / "harness"
RESULTS = ROOT / "results"
TMP = ROOT / "tmp"
DATA = ROOT / "data"
TARGET_ROWS = 4_000_000
VARIANTS = ("upstream", "pr")

LAYERS = {
    # name: (default sources, conflict modes, retries, tag, use_index)
    "A": (["lance", "parquet"], [0, 1], None, "merge_insert_base", None),
    "A0": (["lance", "parquet"], [0], 0, "merge_insert_base", None),
    "B": (["arrow_scanner", "reader"], [0, 1], None, "merge_insert_base", None),
    "P": (["lance"], [0], None, "merge_insert_base_indexed", 1),
    "D": (["lance"], [0], None, "merge_insert_base", None),
}


def python_of(variant: str) -> str:
    return str(ROOT / f"venv-{variant}" / "bin" / "python")


def git_head(variant: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT / f"src-{variant}"), "rev-parse", "HEAD"], text=True
    ).strip()


def child_env(tmpdir: str) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if "proxy" not in k.lower() and not k.startswith(("CARGO", "RUST", "UV_"))
    }
    env["TMPDIR"] = tmpdir
    return env


def run_helper(*args: str) -> dict:
    out = subprocess.run(
        [python_of("upstream"), str(HARNESS / "prep.py"), *args],
        cwd=HARNESS,
        env=child_env(str(TMP)),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


def read_tree(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            with open(os.path.join(root, name), "rb", buffering=0) as f:
                while chunk := f.read(16 << 20):
                    total += len(chunk)
    return total


def source_paths(source: str, tier: str) -> list[Path]:
    if source in ("lance", "reader"):
        return [DATA / f"src-{tier}.lance"]
    return [DATA / f"src-{tier}.parquet"]


def drop_caches() -> None:
    subprocess.run(["sync"], check=True)
    Path("/proc/sys/vm/drop_caches").write_text("3\n")


class Poller(threading.Thread):
    """Track peak TMPDIR usage (allocated blocks) and a coarse child RSS timeline."""

    def __init__(self, pid: int, tmpdir: str, t0: float):
        super().__init__(daemon=True)
        self.pid, self.tmpdir, self.t0 = pid, tmpdir, t0
        self.tmp_peak = 0
        self.spill_files: set[str] = set()
        self.rss_timeline: list[tuple[float, int, int]] = []
        self.stop = threading.Event()

    def run(self) -> None:
        last_sample = -1.0
        while not self.stop.is_set():
            used = 0
            for root, _, files in os.walk(self.tmpdir):
                for name in files:
                    try:
                        used += os.stat(os.path.join(root, name)).st_blocks * 512
                    except FileNotFoundError:
                        continue
                    self.spill_files.add(name)
            self.tmp_peak = max(self.tmp_peak, used)
            now = time.monotonic() - self.t0
            if now - last_sample >= 0.5:
                last_sample = now
                try:
                    status = Path(f"/proc/{self.pid}/status").read_text()
                    fields = dict(
                        line.split(":", 1) for line in status.splitlines() if ":" in line
                    )
                    rss = int(fields["VmRSS"].split()[0])
                    self.rss_timeline.append((round(now, 2), rss, used))
                except (FileNotFoundError, KeyError, ProcessLookupError):
                    pass
            self.stop.wait(0.05)


def measure(variant: str, cell: dict, tmpdir: str, run_id: str) -> dict:
    out_path = RESULTS / "runs" / f"{run_id}.json"
    log_path = RESULTS / "runs" / f"{run_id}.log"
    cmd = [
        python_of(variant),
        str(HARNESS / "run_merge.py"),
        "--tier", cell["tier"],
        "--source", cell["source"],
        "--conflict", str(cell["conflict"]),
        "--competitor-id", str(cell["competitor_id"]),
        "--out", str(out_path),
    ]  # fmt: skip
    if cell["retries"] is not None:
        cmd += ["--retries", str(cell["retries"])]
    if cell["use_index"] is not None:
        cmd += ["--use-index", str(cell["use_index"])]

    with open(log_path, "w") as log:
        t0 = time.monotonic()
        proc = subprocess.Popen(
            cmd, cwd=HARNESS, env=child_env(tmpdir), stdout=log, stderr=log
        )
        poller = Poller(proc.pid, tmpdir, t0)
        poller.start()
        _, status, ru = os.wait4(proc.pid, 0)
        wall = time.monotonic() - t0
        proc.returncode = os.waitstatus_to_exitcode(status)
        poller.stop.set()
        poller.join()

    record = {
        "exit_code": proc.returncode,
        "process_wall_s": wall,
        "user_s": ru.ru_utime,
        "sys_s": ru.ru_stime,
        "cpu_s": ru.ru_utime + ru.ru_stime,
        "peak_rss_kib": ru.ru_maxrss,
        "tmp_peak_bytes": poller.tmp_peak,
        "spill_files": sorted(poller.spill_files),
        "replay_buffer_on_disk": "spill.arrows" in poller.spill_files,
    }
    with open(RESULTS / "runs" / f"{run_id}.rss.json", "w") as f:
        json.dump(poller.rss_timeline, f)
    if proc.returncode == 0:
        child = json.loads(out_path.read_text())
        record.update(child)
        record["spill_bytes_est_wchar"] = (
            child["proc_io"]["wchar"] - child["target_written_bytes"]
        )
        record["spill_bytes_est_write_bytes"] = (
            child["proc_io"]["write_bytes"] - child["target_written_bytes"]
        )
    else:
        record["error_tail"] = log_path.read_text()[-4000:]
    return record


def build_cells(args) -> list[dict]:
    sources, conflicts, retries, tag, use_index = LAYERS[args.layer]
    if args.sources:
        sources = args.sources.split(",")
    if args.conflict is not None:
        conflicts = [int(c) for c in args.conflict.split(",")]
    cells = []
    for tier, source, conflict in itertools.product(
        args.tiers.split(","), sources, conflicts
    ):
        meta = json.loads((DATA / f"src-{tier}.json").read_text())
        cells.append(
            {
                "layer": args.layer,
                "tier": tier,
                "source": source,
                "conflict": conflict,
                "retries": retries,
                "tag": tag,
                "use_index": use_index,
                "cache": args.cache,
                "tmp_kind": "loop2g" if args.tmpdir else "nvme",
                "competitor_id": meta["competitor_id"],
                "source_rows": meta["rows"],
                "source_arrow_bytes": meta["arrow_bytes"],
                "expected_rows": TARGET_ROWS + meta["new_keys"],
            }
        )
    return cells


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", required=True, choices=sorted(LAYERS))
    parser.add_argument("--tiers", required=True)
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--sources")
    parser.add_argument("--conflict")
    parser.add_argument("--cache", default="hot", choices=["hot", "cold"])
    parser.add_argument("--tmpdir", help="parent for per-run TMPDIR (layer D)")
    parser.add_argument("--label", default="")
    parser.add_argument("--raw", default=str(RESULTS / "raw.jsonl"))
    args = parser.parse_args()

    (RESULTS / "runs").mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    heads = {v: git_head(v) for v in VARIANTS}
    cells = build_cells(args)
    total = len(cells) * args.reps * len(VARIANTS)
    done = 0
    for cell in cells:
        for rep in range(args.reps):
            for variant in VARIANTS:
                usage = shutil.disk_usage("/mnt/lance")
                if usage.used / usage.total > 0.80:
                    sys.exit(f"disk usage {usage.used / usage.total:.0%} > 80%, stopping")
                run_id = f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
                restored = run_helper("restore", cell["tag"])
                if args.cache == "hot":
                    warmed = read_tree(DATA / "target.lance")
                    for path in source_paths(cell["source"], cell["tier"]):
                        warmed += read_tree(path)
                else:
                    drop_caches()
                tmp_parent = Path(args.tmpdir) if args.tmpdir else TMP
                tmpdir = tmp_parent / run_id
                tmpdir.mkdir(parents=True)

                record = {
                    "run_id": run_id,
                    "label": args.label,
                    "variant": variant,
                    "commit": heads[variant],
                    "rep": rep,
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    **{k: v for k, v in cell.items() if k != "competitor_id"},
                }
                record.update(measure(variant, cell, str(tmpdir), run_id))
                shutil.rmtree(tmpdir, ignore_errors=True)

                if record["exit_code"] == 0:
                    record["verify"] = run_helper(
                        "verify",
                        cell["tier"],
                        str(cell["expected_rows"]),
                        str(restored["version"]),
                        str(2 if cell["conflict"] else 1),
                    )
                with open(args.raw, "a") as f:
                    f.write(json.dumps(record) + "\n")
                done += 1
                print(
                    f"[{done}/{total}] {args.layer} {cell['tier']} {cell['source']} "
                    f"c={cell['conflict']} {variant} rep={rep} exit={record['exit_code']} "
                    f"wall={record.get('merge_wall_s', float('nan')):.2f}s "
                    f"cpu={record['cpu_s']:.1f}s rss={record['peak_rss_kib'] / 1024:.0f}MiB "
                    f"tmp_peak={record['tmp_peak_bytes'] / 2**20:.0f}MiB "
                    f"attempts={record.get('commit_attempts')} "
                    f"verify={record.get('verify', {}).get('ok')}",
                    flush=True,
                )
    run_helper("restore", "merge_insert_base")


if __name__ == "__main__":
    main()
