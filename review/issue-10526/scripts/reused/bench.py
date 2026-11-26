#!/usr/bin/env python3
import argparse
import json
import os
import re
import resource
import struct
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

WIDE_ROWS = 25_000
WIDE_BYTES = 180_000
NARROW_ROWS = 10_000_000
WORD_COUNT = 4_096
SEED = 10526
DATASETS = (
    "wide-unique",
    "wide-unique-8k",
    "wide-low-card",
    "wide-repeated",
    "wide-template",
    "wide-clustered",
    "wide-mixed",
    "wide-constant",
    "narrow",
)


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

        rng = np.random.default_rng(SEED)
        if kind == "wide-unique":
            column = wide_strings(WIDE_ROWS)
        elif kind == "wide-unique-8k":
            column = wide_strings(8_000)
        elif kind == "narrow":
            column = pa.array(np.arange(NARROW_ROWS, dtype=np.int64))
        else:
            with pa.memory_map(str(directory / "wide-unique.arrow"), "r") as source:
                unique = pa.ipc.open_file(source).get_batch(0).column(0)
                if kind == "wide-low-card":
                    indices = np.resize(np.arange(10, dtype=np.int32), WIDE_ROWS)
                    rng.shuffle(indices)
                elif kind == "wide-repeated":
                    indices = np.repeat(np.arange(100, dtype=np.int32), 80)
                elif kind == "wide-template":
                    indices = np.arange(WIDE_ROWS, dtype=np.int32)
                    indices[
                        rng.choice(
                            np.arange(1, WIDE_ROWS), WIDE_ROWS // 20 - 1, replace=False
                        )
                    ] = 0
                elif kind == "wide-clustered":
                    indices = np.repeat(np.arange(50, dtype=np.int32), 500)
                elif kind == "wide-constant":
                    indices = np.zeros(WIDE_ROWS, dtype=np.int32)
                else:
                    wide_count = WIDE_ROWS * 95 // 100
                    short_count = WIDE_ROWS * 4 // 100
                    unique = pa.concat_arrays(
                        [
                            unique.slice(0, wide_count),
                            pa.array(
                                [
                                    f"{row:08d}" + " short value" * 8
                                    for row in range(short_count)
                                ]
                                + ["", None],
                                type=pa.large_string(),
                            ),
                        ]
                    )
                    indices = np.repeat(
                        np.arange(len(unique), dtype=np.int32),
                        [1] * (len(unique) - 2) + [WIDE_ROWS // 200] * 2,
                    )
                    rng.shuffle(indices)
                column = pc.take(unique, indices)

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


def page_row_counts(path: Path) -> list[int]:
    footer = struct.Struct("<QQQIIHH4s")
    with path.open("rb") as file:
        file.seek(-footer.size, os.SEEK_END)
        _, offsets, _, _, columns, major, minor, magic = footer.unpack(
            file.read(footer.size)
        )
        assert (columns, major, minor, magic) == (1, 2, 2, b"LANC")
        file.seek(offsets)
        start, length = struct.unpack("<QQ", file.read(16))
        file.seek(start)
        column_metadata = file.read(length)

    proto_dir = Path(os.environ["LANCE_BENCH_PROTO_DIR"])
    decoded = subprocess.run(
        [
            "protoc",
            f"--proto_path={proto_dir}",
            "--decode=lance.file.v2.ColumnMetadata",
            "file2.proto",
        ],
        input=column_metadata,
        stdout=subprocess.PIPE,
        check=True,
    )
    return [
        int(rows) for rows in re.findall(rb"^  length: (\d+)$", decoded.stdout, re.M)
    ]


def measure(
    input_path: Path,
    scratch: Path,
    writers: int,
    rows: int | None,
    file_stats: bool,
    keep: Path | None,
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
            cpu_start = time.process_time()
            start = time.perf_counter()
            barrier.wait()
            for job in jobs:
                job.result()
            elapsed = time.perf_counter() - start
            cpu_seconds = time.process_time() - cpu_start
        statistics = {
            "dataset": input_path.stem,
            "lance_version": lance.__version__,
            "rows_per_writer": batches[0].num_rows,
            "writers": writers,
            "cpu_threads": int(os.environ["LANCE_CPU_THREADS"]),
            "pre_write_rss_kib": pre_write_rss_kib,
            "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "write_wall_seconds": elapsed,
            "write_cpu_seconds": cpu_seconds,
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
            page_rows = page_row_counts(file_path)
            assert len(page_rows) == len(pages)
            assert sum(page_rows) == batches[0].num_rows
            column = batches[0].column(0)
            lengths = (
                None if pa.types.is_int64(column.type) else pc.binary_length(column)
            )
            row_offset = 0
            page_details = []
            for page, num_rows in zip(pages, page_rows):
                value_bytes = (
                    num_rows * 8
                    if lengths is None
                    else pc.sum(lengths.slice(row_offset, num_rows)).as_py() or 0
                )
                page_details.append(
                    {
                        "rows": num_rows,
                        "raw_value_bytes": value_bytes,
                        "encoded_bytes": sum(buffer.size for buffer in page.buffers),
                        "encoding": page.encoding,
                    }
                )
                row_offset += num_rows
            statistics.update(
                file_bytes=file_path.stat().st_size,
                pages=len(pages),
                page_rows=page_rows,
                raw_value_bytes=sum(page["raw_value_bytes"] for page in page_details),
                max_uncompressed_value_bytes=max(
                    page["raw_value_bytes"] for page in page_details
                ),
                max_encoded_page_bytes=max(
                    page["encoded_bytes"] for page in page_details
                ),
                page_details=page_details,
            )
            if keep is not None:
                paths[0].rename(keep)

    print(json.dumps(statistics), flush=True)


def check_files(baseline_path: Path, fix_path: Path) -> None:
    baseline = json.loads(baseline_path.read_text())
    fix = json.loads(fix_path.read_text())
    assert fix["dataset"] == baseline["dataset"]
    checks = {}
    details = {}
    if fix["dataset"] == "wide-unique":
        ratios = [run["raw_value_bytes"] / run["file_bytes"] for run in (baseline, fix)]
        details["compression_ratios_baseline_fix"] = ratios
        checks["compression_near_threefold"] = all(
            2.5 <= ratio <= 3.5 for ratio in ratios
        )
    if fix["dataset"] in ("wide-low-card", "wide-constant", "narrow"):
        checks.update(
            unchanged_page_count=fix["pages"] == baseline["pages"],
            unchanged_file_bytes=fix["file_bytes"] == baseline["file_bytes"],
        )
    print(json.dumps({"dataset": fix["dataset"], **details, **checks}), flush=True)
    if not all(checks.values()):
        raise SystemExit(1)


def read_output(dataset_path: Path, input_path: Path, operation: str) -> None:
    import lance

    rows = (
        NARROW_ROWS
        if input_path.stem == "narrow"
        else (
            8_000
            if input_path.stem in ("wide-unique-8k", "wide-repeated")
            else WIDE_ROWS
        )
    )
    expected = read_batch(input_path, None) if operation == "verify" else None
    indices = (
        sorted(np.random.default_rng(SEED).choice(rows, 128, replace=False).tolist())
        if operation == "take"
        else None
    )
    start = time.perf_counter()
    dataset = lance.dataset(dataset_path)
    if indices is None:
        offset = 0
        for batch in dataset.to_batches(batch_size=1024):
            if expected is not None:
                assert batch.equals(expected.slice(offset, batch.num_rows)), offset
            offset += batch.num_rows
        assert offset == rows
    else:
        assert dataset.take(indices).num_rows == len(indices)
    print(
        json.dumps(
            {
                "dataset": input_path.stem,
                "operation": operation,
                "rows": len(indices) if indices is not None else rows,
                "indices": indices,
                "wall_seconds": time.perf_counter() - start,
                "process_peak_rss_kib": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss,
            }
        ),
        flush=True,
    )


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
    measure_args.add_argument("--keep", type=Path)
    read_args = commands.add_parser("read")
    read_args.add_argument("dataset", type=Path)
    read_args.add_argument("input", type=Path)
    read_args.add_argument("operation", choices=("verify", "scan", "take"))
    check_args = commands.add_parser("check-files")
    check_args.add_argument("baseline", type=Path)
    check_args.add_argument("fix", type=Path)
    args = parser.parse_args()
    if args.command == "generate":
        generate(args.directory)
    elif args.command == "measure":
        measure(
            args.input,
            args.scratch,
            args.writers,
            args.rows,
            args.file_stats,
            args.keep,
        )
    elif args.command == "read":
        read_output(args.dataset, args.input, args.operation)
    else:
        check_files(args.baseline, args.fix)


if __name__ == "__main__":
    main()
