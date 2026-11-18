#!/usr/bin/env python3
import argparse
import json
import os
import resource
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

WIDE_ROWS = 8_000
WIDE_BYTES = 180_000
NARROW_ROWS = 10_000_000
WORD_COUNT = 4_096
SEED = 10526
DATASETS = ("wide-unique", "wide-repeated", "narrow")


def wide_strings(rows: int) -> pa.Array:
    rng = np.random.default_rng(SEED)
    word_ids = rng.choice(26**7, size=WORD_COUNT, replace=False)
    alphabet = np.array(list(b"abcdefghijklmnopqrstuvwxyz"), dtype=np.uint8)
    words = np.full((WORD_COUNT, 8), ord(" "), dtype=np.uint8)
    for position in range(6, -1, -1):
        words[:, position] = alphabet[word_ids % 26]
        word_ids //= 26
    count_per_row = (WIDE_BYTES - 8) // words.shape[1]
    encoded = np.empty((rows, WIDE_BYTES), dtype=np.uint8)
    prefixes = np.array([f"{row:08d}" for row in range(rows)], dtype="S8")
    encoded[:, :8] = prefixes.view(np.uint8).reshape(rows, 8)
    for start in range(0, rows, 128):
        chunk = encoded[start : start + 128, 8:]
        indexes = rng.integers(
            0, WORD_COUNT, (len(chunk), count_per_row), dtype=np.uint16
        )
        chunk[:] = words[indexes].reshape(len(chunk), -1)
    offsets = np.arange(rows + 1, dtype=np.int64) * WIDE_BYTES
    return pa.Array.from_buffers(
        pa.large_string(),
        rows,
        [None, pa.py_buffer(offsets), pa.py_buffer(encoded)],
    )


def generate(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for kind in DATASETS:
        path = directory / f"{kind}.arrow"
        if path.exists():
            print(json.dumps({"dataset": kind, "ipc_bytes": path.stat().st_size}))
            continue

        if kind == "wide-unique":
            column = wide_strings(WIDE_ROWS)
        elif kind == "wide-repeated":
            with pa.memory_map(str(directory / "wide-unique.arrow"), "r") as source:
                unique = pa.ipc.open_file(source).get_batch(0).column(0)
                indices = np.repeat(np.arange(100, dtype=np.int32), 80)
                column = pc.take(unique, indices)
        else:
            column = pa.array(np.arange(NARROW_ROWS, dtype=np.int64))

        batch = pa.record_batch([column], names=["payload"])
        pending = path.with_suffix(".partial")
        with pa.OSFile(str(pending), "wb") as sink:
            with pa.ipc.new_file(sink, batch.schema) as writer:
                writer.write_batch(batch)
        pending.rename(path)
        print(
            json.dumps(
                {
                    "dataset": kind,
                    "rows": batch.num_rows,
                    "ipc_bytes": path.stat().st_size,
                }
            ),
            flush=True,
        )
        del batch, column


def read_batch(path: Path, rows: int | None) -> pa.RecordBatch:
    if rows is not None:
        with pa.memory_map(str(path), "r") as source:
            reader = pa.ipc.open_file(source)
            assert reader.num_record_batches == 1
            batch = reader.get_batch(0)
            prefix = pc.take(batch.column(0), np.arange(rows, dtype=np.int32))
            return pa.record_batch([prefix], schema=batch.schema)
    with pa.OSFile(str(path), "rb") as source:
        reader = pa.ipc.open_file(source)
        assert reader.num_record_batches == 1
        return reader.get_batch(0)


def current_rss_kib() -> int:
    with Path("/proc/self/smaps_rollup").open() as breakdown:
        for line in breakdown:
            if line.startswith("Rss:"):
                return int(line.split()[1])
    raise RuntimeError("Rss is missing from /proc/self/smaps_rollup")


def measure(
    input_path: Path,
    scratch: Path,
    writers: int,
    rows: int | None,
    file_stats: bool,
) -> None:
    import lance
    from lance.file import LanceFileReader

    batches = [read_batch(input_path, rows) for _ in range(writers)]

    with tempfile.TemporaryDirectory(dir=scratch, prefix="write-") as directory:
        paths = [Path(directory) / f"dataset-{index}" for index in range(writers)]
        barrier = Barrier(writers + 1)

        def write(batch: pa.RecordBatch, path: Path) -> None:
            barrier.wait()
            lance.write_dataset(
                batch,
                path,
                data_storage_version="2.2",
                max_rows_per_group=batch.num_rows,
                max_rows_per_file=batch.num_rows,
            )

        with ThreadPoolExecutor(max_workers=writers) as pool:
            jobs = [
                pool.submit(write, batch, path) for batch, path in zip(batches, paths)
            ]
            pre_write_rss_kib = current_rss_kib()
            start = time.perf_counter()
            barrier.wait()
            for job in jobs:
                job.result()
            elapsed = time.perf_counter() - start
        statistics = {
            "dataset": input_path.stem,
            "lance_version": lance.__version__,
            "rows_per_writer": batches[0].num_rows,
            "writers": writers,
            "cpu_threads": int(os.environ["LANCE_CPU_THREADS"]),
            "pre_write_rss_kib": pre_write_rss_kib,
            "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "write_wall_seconds": elapsed,
        }

        if file_stats:
            assert writers == 1
            dataset = lance.dataset(paths[0])
            assert dataset.count_rows() == batches[0].num_rows
            fragments = dataset.get_fragments()
            assert len(fragments) == 1
            files = fragments[0].metadata.files
            assert len(files) == 1
            file_path = paths[0] / "data" / files[0].path
            metadata = LanceFileReader(str(file_path)).metadata()
            assert len(metadata.columns) == 1
            pages = metadata.columns[0].pages
            statistics.update(
                file_bytes=file_path.stat().st_size,
                pages=len(pages),
                max_page_bytes=max(
                    sum(buffer.size for buffer in page.buffers) for page in pages
                ),
            )

    print(json.dumps(statistics), flush=True)


def check_files(baseline_path: Path, fix_path: Path) -> None:
    baseline = json.loads(baseline_path.read_text())
    fix = json.loads(fix_path.read_text())
    assert fix["dataset"] == baseline["dataset"]
    if fix["dataset"] == "wide-unique":
        checks = {
            "wide_unique_max_page": fix["max_page_bytes"] <= 32 * 1024**2 + WIDE_BYTES,
            "wide_unique_file_bytes": fix["file_bytes"] * 100
            <= baseline["file_bytes"] * 102,
        }
    else:
        checks = {
            "unchanged_page_count": fix["pages"] == baseline["pages"],
            "unchanged_file_bytes": fix["file_bytes"] == baseline["file_bytes"],
        }
    print(json.dumps({"dataset": fix["dataset"], **checks}), flush=True)
    if not all(checks.values()):
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    generate_args = commands.add_parser("generate")
    generate_args.add_argument("directory", type=Path)
    measure_args = commands.add_parser("measure")
    measure_args.add_argument("input", type=Path)
    measure_args.add_argument("scratch", type=Path)
    measure_args.add_argument("--writers", type=int, required=True)
    measure_args.add_argument("--rows", type=int)
    measure_args.add_argument("--file-stats", action="store_true")
    check_args = commands.add_parser("check-files")
    check_args.add_argument("baseline", type=Path)
    check_args.add_argument("fix", type=Path)
    args = parser.parse_args()
    if args.command == "generate":
        generate(args.directory)
    elif args.command == "measure":
        measure(args.input, args.scratch, args.writers, args.rows, args.file_stats)
    else:
        check_files(args.baseline, args.fix)


if __name__ == "__main__":
    main()
