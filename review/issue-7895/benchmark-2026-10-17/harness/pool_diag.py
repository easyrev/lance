#!/usr/bin/env python3
"""Diagnose Arrow-pool and RSS state across a forced merge retry."""

from __future__ import annotations

import argparse
import contextlib
import json
import resource
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import lance
import pyarrow as pa
import pyarrow.dataset as pads
from lance.types import WriteSource

from common import TARGET_URI, parquet_source_dir


def memory_state(pool: pa.MemoryPool) -> dict:
    state = {
        "t_s": time.monotonic(),
        "pool_bytes": pool.bytes_allocated(),
        "pool_max": pool.max_memory(),
        "pool_total": pool.total_bytes_allocated(),
        "pool_allocations": pool.num_allocations(),
    }
    for path in (Path("/proc/self/smaps_rollup"), Path("/proc/self/status")):
        for line in path.read_text().splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key in {
                "Rss",
                "Pss",
                "Private_Clean",
                "Private_Dirty",
                "Anonymous",
                "VmRSS",
                "RssAnon",
                "RssFile",
                "RssShmem",
            }:
                state[f"{path.name}_{key}_kib"] = int(value.split()[0])
    return state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=(
            "reused",
            "fresh",
            "low_readahead",
            "small_batch",
            "bounded",
        ),
        required=True,
    )
    parser.add_argument(
        "--pool-backend", choices=("default", "system"), default="default"
    )
    parser.add_argument("--tier", default="1g")
    parser.add_argument("--competitor-id", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    parent_pool = (
        pa.default_memory_pool()
        if args.pool_backend == "default"
        else pa.system_memory_pool()
    )
    pool = pa.proxy_memory_pool(parent_pool)
    dataset = pads.dataset(parquet_source_dir(args.tier), format="parquet")
    events: list[dict] = []
    started = time.monotonic()

    def record(event: str, **extra) -> None:
        state = memory_state(pool)
        state["t_s"] -= started
        events.append({"event": event, **state, **extra})

    scanner_options = {"memory_pool": pool}
    if args.mode in ("small_batch", "bounded"):
        scanner_options["batch_size"] = 16_384
    if args.mode in ("low_readahead", "bounded"):
        scanner_options.update(batch_readahead=1, fragment_readahead=1)

    reused_scanner = None
    if args.mode == "reused":
        reused_scanner = pads.Scanner.from_dataset(dataset, **scanner_options)

    factory_calls = 0

    def open_reader():
        nonlocal factory_calls
        factory_calls += 1
        record("factory_enter", call=factory_calls)
        scanner = reused_scanner or pads.Scanner.from_dataset(dataset, **scanner_options)
        reader = scanner.to_reader()
        record("factory_return", call=factory_calls)
        return reader

    source = WriteSource(dataset.schema, open_reader)
    commits = 0

    @contextlib.contextmanager
    def commit_lock(version):
        nonlocal commits
        commits += 1
        record("commit_enter", attempt=commits, version=version)
        if commits == 1:
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(
                    lambda: lance.dataset(TARGET_URI).update(
                        {"label": "'competitor'"},
                        where=f"id = {args.competitor_id}",
                        conflict_retries=0,
                    )
                ).result(timeout=600)
            record("competitor_complete", attempt=commits)
        yield
        record("commit_exit", attempt=commits)

    target = lance.dataset(TARGET_URI, commit_lock=commit_lock)
    start_version = target.version
    record("before_execute")
    ru0 = resource.getrusage(resource.RUSAGE_SELF)
    t0 = time.monotonic()
    stats = (
        target.merge_insert("id")
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .retry_timeout(__import__("datetime").timedelta(seconds=3600))
        .execute(source)
    )
    elapsed = time.monotonic() - t0
    ru1 = resource.getrusage(resource.RUSAGE_SELF)
    record("after_execute")

    result = {
        "mode": args.mode,
        "pool_backend_requested": args.pool_backend,
        "tier": args.tier,
        "factory_calls": factory_calls,
        "commit_attempts": commits,
        "start_version": start_version,
        "end_version": lance.dataset(TARGET_URI).version,
        "wall_s": elapsed,
        "user_s": ru1.ru_utime - ru0.ru_utime,
        "sys_s": ru1.ru_stime - ru0.ru_stime,
        "max_rss_kib": ru1.ru_maxrss,
        "stats": dict(stats),
        "pool_backend": pool.backend_name,
        "events": events,
    }
    Path(args.out).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
