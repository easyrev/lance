#!/usr/bin/env python3
"""Measure index directories left by lost compaction commits.

This script races one local ``compact_files`` call against one ``delete`` call
on the same dataset.  Each successful delete forces the concurrent compaction
to lose a commit while remapping an IVF_PQ index.  At the end, the script reads
every available dataset version, gathers all referenced index segment UUIDs,
and reports directories under ``_indices/`` that no version references.

The dataset is deliberately small.  Pass a URI on a data disk, for example:

    uv run python review/issue-7207/bench/measure_lost_indices.py \
      --uri /data/issue-7207-run --output /tmp/issue-7207-run.json

The script never removes the target dataset.  It refuses to start when the
target directory already contains files.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

import lance
import numpy as np
import pyarrow as pa


def git_state(repo: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {"commit": commit, "dirty": bool(status), "changes": status}


def make_batch(start: int, count: int, dimension: int, seed: int) -> pa.Table:
    rng = np.random.default_rng(seed)
    flat_vectors = rng.random(count * dimension, dtype=np.float32)
    vectors = pa.FixedSizeListArray.from_arrays(
        pa.array(flat_vectors, type=pa.float32()), dimension
    )
    return pa.table(
        {
            "id": pa.array(range(start, start + count), type=pa.int64()),
            "vector": vectors,
        }
    )


def create_dataset(
    uri: str,
    rows: int,
    rows_per_fragment: int,
    dimension: int,
    seed: int,
) -> None:
    batch = make_batch(0, rows, dimension, seed)
    dataset = lance.write_dataset(
        batch,
        uri,
        mode="create",
        max_rows_per_file=rows_per_fragment,
        max_rows_per_group=rows_per_fragment,
    )
    dataset.create_index(
        "vector",
        "IVF_PQ",
        num_partitions=4,
        num_sub_vectors=4,
    )


def run_guarded(
    barrier: threading.Barrier,
    operation: Callable[[], Any],
) -> dict[str, Any]:
    barrier.wait(timeout=30)
    started = time.monotonic()
    try:
        value = operation()
        return {
            "status": "ok",
            "value": str(value),
            "seconds": time.monotonic() - started,
        }
    except Exception as error:  # noqa: BLE001 - preserve the injected race error
        return {
            "status": "error",
            "error_type": type(error).__name__,
            "error": str(error),
            "seconds": time.monotonic() - started,
        }


def run_race(
    uri: str,
    deleted_start: int,
    deleted_rows: int,
    target_rows_per_fragment: int,
) -> dict[str, Any]:
    barrier = threading.Barrier(3)

    def compact() -> Any:
        dataset = lance.dataset(uri)
        return dataset.optimize.compact_files(
            target_rows_per_fragment=target_rows_per_fragment,
            materialize_deletions=True,
            materialize_deletions_threshold=0.01,
            num_threads=1,
            defer_index_remap=False,
        )

    def delete() -> Any:
        dataset = lance.dataset(uri)
        predicate = (
            f"id >= {deleted_start} and id < {deleted_start + deleted_rows}"
        )
        return dataset.delete(
            predicate,
            conflict_retries=1,
            retry_timeout=timedelta(seconds=1),
        )

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as executor:
        compact_future = executor.submit(run_guarded, barrier, compact)
        delete_future = executor.submit(run_guarded, barrier, delete)
        barrier.wait(timeout=30)
        compact_result = compact_future.result()
        delete_result = delete_future.result()

    return {
        "seconds": time.monotonic() - started,
        "compact": compact_result,
        "delete": delete_result,
    }


def is_lost_commit(result: dict[str, Any]) -> bool:
    if result["status"] != "error":
        return False
    message = result.get("error", "").lower()
    return "commit conflict" in message or "preempted" in message


def referenced_index_ids(uri: str) -> set[str]:
    dataset = lance.dataset(uri)
    referenced: set[str] = set()
    for version_info in dataset.versions():
        version_dataset = lance.dataset(uri, version=version_info["version"])
        for index in version_dataset.describe_indices():
            referenced.update(str(segment.uuid) for segment in index.segments)
    return referenced


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def orphan_directory_stats(uri: Path, referenced: set[str]) -> dict[str, Any]:
    indices_dir = uri / "_indices"
    directories = {
        entry.name: directory_size(entry)
        for entry in indices_dir.iterdir()
        if entry.is_dir()
    }
    unreferenced = {
        name: size for name, size in directories.items() if name not in referenced
    }
    return {
        "index_directory_count": len(directories),
        "referenced_index_id_count": len(referenced),
        "unreferenced_count": len(unreferenced),
        "unreferenced_bytes": sum(unreferenced.values()),
        "unreferenced_directories": dict(sorted(unreferenced.items())),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--uri",
        required=True,
        help="New local directory for the generated Lance table",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON result path")
    parser.add_argument("--target-lost", type=int, default=8)
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--rows", type=int, default=8192)
    parser.add_argument("--rows-per-fragment", type=int, default=256)
    parser.add_argument("--dimension", type=int, default=16)
    parser.add_argument("--seed", type=int, default=7207)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Repository used to record the tested git commit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if "://" in args.uri:
        raise SystemExit("This measurement script currently supports local paths only")
    dataset_path = Path(args.uri).expanduser().resolve()
    if dataset_path.exists() and any(dataset_path.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty dataset path: {dataset_path}")
    if args.output is not None and args.output.resolve().is_relative_to(dataset_path):
        raise SystemExit("--output must be outside the generated dataset")
    if args.target_lost < 1:
        raise SystemExit("--target-lost must be positive")
    if args.rows_per_fragment < 2:
        raise SystemExit("--rows-per-fragment must be at least 2")

    max_attempts = args.max_attempts or max(args.target_lost * 4, args.target_lost)
    max_deletions = args.rows // max(args.rows_per_fragment // 2, 1)
    if max_attempts > max_deletions:
        raise SystemExit(
            "--max-attempts exceeds the number of non-overlapping delete ranges; "
            "increase --rows or reduce --max-attempts"
        )

    started = time.monotonic()
    create_dataset(
        str(dataset_path),
        args.rows,
        args.rows_per_fragment,
        args.dimension,
        args.seed,
    )
    setup_seconds = time.monotonic() - started

    rounds: list[dict[str, Any]] = []
    lost_commits = 0
    delete_step = max(args.rows_per_fragment // 2, 1)
    measurement_started = time.monotonic()
    for attempt in range(max_attempts):
        result = run_race(
            str(dataset_path),
            attempt * delete_step,
            delete_step,
            args.rows_per_fragment * 4,
        )
        result["attempt"] = attempt + 1
        rounds.append(result)
        if is_lost_commit(result["compact"]):
            lost_commits += 1
        if lost_commits >= args.target_lost:
            break

    wall_seconds = time.monotonic() - measurement_started
    referenced = referenced_index_ids(str(dataset_path))
    orphan_stats = orphan_directory_stats(dataset_path, referenced)
    report = {
        "git": git_state(args.repo.resolve()),
        "dataset_uri": str(dataset_path),
        "target_lost_commits": args.target_lost,
        "lost_commits": lost_commits,
        "attempts": len(rounds),
        "setup_seconds": setup_seconds,
        "wall_seconds": wall_seconds,
        "rounds": rounds,
        **orphan_stats,
    }

    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    return 0 if lost_commits >= args.target_lost else 1


if __name__ == "__main__":
    raise SystemExit(main())
