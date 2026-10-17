# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright The Lance Authors

"""One measured merge_insert, run in a fresh process by driver.py.

Process-wide CPU, peak RSS and spill-directory usage are taken by the driver
(wait4 + polling).  This process reports what only it can see: the merge's own
wall/CPU window, Lance IO stats, /proc/self/io and commit-attempt timestamps.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import resource
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import lance
import pyarrow.dataset as pads

from common import TARGET_URI, lance_source_uri, parquet_source_dir


def proc_io() -> dict:
    with open("/proc/self/io") as f:
        return {k: int(v) for k, v in (line.split(": ") for line in f)}


def build_source(kind: str, tier: str):
    """Return (source object passed to execute, lance source dataset or None)."""
    if kind == "lance":
        src = lance.dataset(lance_source_uri(tier), version=1)
        return src, src
    if kind == "parquet":
        return pads.dataset(parquet_source_dir(tier), format="parquet"), None
    if kind == "arrow_scanner":
        parquet = pads.dataset(parquet_source_dir(tier), format="parquet")
        return pads.Scanner.from_dataset(parquet), None
    if kind == "reader":
        src = lance.dataset(lance_source_uri(tier), version=1)
        return src.scanner().to_reader(), src
    raise ValueError(f"unknown source kind {kind!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--retries", type=int, default=None)
    parser.add_argument("--conflict", type=int, default=0)
    parser.add_argument("--competitor-id", type=int, required=True)
    parser.add_argument("--retry-timeout-s", type=int, default=3600)
    parser.add_argument("--use-index", type=int, default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    io_start = proc_io()
    commits: list[float] = []

    @contextlib.contextmanager
    def commit_lock(version):
        commits.append(time.monotonic())
        if args.conflict and len(commits) == 1:
            # Same shape as `_source_retry_commit_lock` in test_dataset.py: a
            # competing commit lands between our first attempt and its commit.
            # It updates a key the source also updates, so the conflict is
            # row-level and the merge must re-execute exactly once.
            def compete():
                lance.dataset(TARGET_URI).update(
                    {"label": "'competitor'"},
                    where=f"id = {args.competitor_id}",
                    conflict_retries=0,
                )

            t = time.monotonic()
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(compete).result(timeout=600)
            commits.append(-(time.monotonic() - t))  # competitor duration marker
        yield

    target = lance.dataset(TARGET_URI, commit_lock=commit_lock)
    start_version = target.version
    source, lance_src = build_source(args.source, args.tier)

    builder = target.merge_insert("id").when_matched_update_all()
    builder = builder.when_not_matched_insert_all()
    if args.retries is not None:
        builder = builder.conflict_retries(args.retries)
    builder = builder.retry_timeout(timedelta(seconds=args.retry_timeout_s))
    if args.use_index is not None:
        builder = builder.use_index(bool(args.use_index))

    target.io_stats_incremental()
    if lance_src is not None:
        lance_src.io_stats_incremental()

    ru0 = resource.getrusage(resource.RUSAGE_SELF)
    t0 = time.monotonic()
    stats = builder.execute(source)
    t1 = time.monotonic()
    ru1 = resource.getrusage(resource.RUSAGE_SELF)

    target_io = target.io_stats_incremental()
    src_io = lance_src.io_stats_incremental() if lance_src is not None else None
    io_end = proc_io()

    commit_times = [c - t0 for c in commits if c >= 0]
    competitor_s = [-c for c in commits if c < 0]
    result = {
        "merge_wall_s": t1 - t0,
        "merge_user_s": ru1.ru_utime - ru0.ru_utime,
        "merge_sys_s": ru1.ru_stime - ru0.ru_stime,
        "stats": dict(stats),
        "commit_attempts": len(commit_times),
        "commit_times_s": commit_times,
        "competitor_s": competitor_s[0] if competitor_s else None,
        "start_version": start_version,
        "end_version": lance.dataset(TARGET_URI).version,
        "target_read_bytes": target_io.read_bytes,
        "target_written_bytes": target_io.written_bytes,
        "target_write_iops": target_io.write_iops,
        "source_read_bytes": src_io.read_bytes if src_io is not None else None,
        "proc_io": {k: io_end[k] - io_start[k] for k in io_end},
        "lance_version": lance.__version__,
        "lance_file": lance.__file__,
    }
    with open(args.out, "w") as f:
        json.dump(result, f)


if __name__ == "__main__":
    main()
