"""Reproduce #9505 in a fresh process. Run with the checkout's uv environment."""

import argparse
import itertools
import json
import os
import resource
import threading
import time
from pathlib import Path

import lance
import numpy as np
import psutil
import pyarrow as pa
import pyarrow.compute as pc


def batches(rows, columns, binary_bytes, batch_rows, offset=0, binary_min_bytes=0):
    rng = np.random.default_rng(9505)
    for start in range(0, rows, batch_rows):
        count = min(batch_rows, rows - start)
        fields = {"id": pa.array(np.arange(start + offset, start + offset + count))}
        for col in range(columns - 1):
            fields[f"c{col}"] = pa.array(rng.integers(0, 2**40, count, dtype=np.int64))
        if binary_bytes:
            # Use independent backing bytes and values in each batch.
            if binary_min_bytes:
                lengths = rng.integers(binary_min_bytes, binary_bytes + 1, count)
                offsets = np.concatenate(([0], np.cumsum(lengths))).astype(np.int64)
            else:
                offsets = np.arange(count + 1, dtype=np.int64) * binary_bytes
            payload = rng.integers(0, 256, int(offsets[-1]), dtype=np.uint8)
            fields["payload"] = pa.LargeBinaryArray.from_buffers(
                pa.large_binary(),
                count,
                [None, pa.py_buffer(offsets), pa.py_buffer(payload)],
            )
            fields["new_payload"] = pa.array([b""] * count, type=pa.large_binary())
        yield pa.record_batch(fields)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["generate", "execute", "analyze"])
    parser.add_argument("--uri", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rows", type=int, default=2_000_000)
    parser.add_argument("--columns", type=int, default=44)
    parser.add_argument("--binary-bytes", type=int, default=0)
    parser.add_argument("--binary-min-bytes", type=int, default=0)
    parser.add_argument("--batch-rows", type=int, default=32768)
    parser.add_argument("--fragment-rows", type=int, default=100_000)
    parser.add_argument("--source-rows", type=int, default=100)
    parser.add_argument("--source-binary-bytes", type=int, default=0)
    parser.add_argument(
        "--source", choices=["materialized", "streaming"], default="streaming"
    )
    parser.add_argument("--full-schema", action="store_true")
    parser.add_argument("--retries", type=int, default=10)
    parser.add_argument("--write-mode", default="rewrite_rows")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    meta = vars(args) | {
        "lance_version": lance.__version__,
        "lance_module": lance.__file__,
        "pool_bytes": os.environ.get("LANCE_MEM_POOL_SIZE"),
        "cpu_count": os.cpu_count(),
        "pid": os.getpid(),
    }
    output.write_text(json.dumps(meta | {"status": "started"}, indent=2))
    if args.operation == "generate":
        data = batches(
            args.rows,
            args.columns,
            args.binary_bytes,
            args.batch_rows,
            binary_min_bytes=args.binary_min_bytes,
        )
        first = next(data)
        reader = pa.RecordBatchReader.from_batches(
            first.schema, itertools.chain([first], data)
        )
        start = time.perf_counter()
        ds = lance.write_dataset(
            reader,
            args.uri,
            max_rows_per_file=args.fragment_rows,
            max_rows_per_group=args.batch_rows,
            data_storage_version="2.2",
        )
        meta.update(
            seconds=time.perf_counter() - start, fragments=len(ds.get_fragments())
        )
    else:
        ds = lance.dataset(args.uri)
        # Restore the original data before each measured merge.
        if ds.version != 1:
            ds = ds.checkout_version(1)
            ds.restore()
        rows = ds.count_rows()
        source_rows = args.source_rows
        meta.update(
            target_rows=rows,
            target_columns=len(ds.schema),
            target_fragments=len(ds.get_fragments()),
        )
        for generation_arg in ("rows", "columns", "binary_bytes", "fragment_rows"):
            meta.pop(generation_arg)
        source_start = time.perf_counter()
        if args.full_schema:
            generated = batches(
                source_rows, args.columns, args.binary_bytes, args.batch_rows
            )
            first = next(generated)
            reader = pa.RecordBatchReader.from_batches(
                first.schema, itertools.chain([first], generated)
            )
            source = reader.read_all() if args.source == "materialized" else reader
            keys = np.arange(source_rows)
        else:
            keys = np.linspace(0, rows - 1, source_rows, dtype=np.int64)
            source = pa.table(
                {
                    "id": keys,
                    "c0": np.full(source_rows, -9505, dtype=np.int64),
                    "c1": np.full(source_rows, -10077, dtype=np.int64),
                }
            )
            if args.source_binary_bytes:
                rng = np.random.default_rng(10077)
                payload = rng.integers(
                    0, 256, source_rows * args.source_binary_bytes, dtype=np.uint8
                )
                offsets = (
                    np.arange(source_rows + 1, dtype=np.int64)
                    * args.source_binary_bytes
                )
                source = pa.table(
                    {
                        "id": keys,
                        "new_payload": pa.LargeBinaryArray.from_buffers(
                            pa.large_binary(),
                            source_rows,
                            [None, pa.py_buffer(offsets), pa.py_buffer(payload)],
                        ),
                    }
                )
        meta["source_prepare_seconds"] = time.perf_counter() - source_start
        meta["source_fields"] = source.schema.names
        builder = (
            ds.merge_insert("id")
            .when_matched_update_all()
            .use_index(False)
            .write_mode(args.write_mode)
            .conflict_retries(args.retries)
        )
        if args.full_schema:
            builder = builder.when_not_matched_insert_all()
        output.with_suffix(".explain.txt").write_text(
            builder.explain_plan(source.schema)
        )
        if args.source == "streaming" and isinstance(source, pa.Table):
            source = source.to_reader(max_chunksize=args.batch_rows)
        process = psutil.Process()
        cgroup_name = Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1]
        cgroup_path = Path("/sys/fs/cgroup") / cgroup_name.lstrip("/")
        meta["cgroup"] = cgroup_name
        meta["cgroup_memory_max"] = (cgroup_path / "memory.max").read_text().strip()
        baseline_rss = process.memory_info().rss
        samples = []
        stop = threading.Event()

        def sample():
            with output.with_suffix(".rss.jsonl").open("w", buffering=1) as log:
                while not stop.wait(0.01):
                    status = {}
                    for line in Path("/proc/self/status").read_text().splitlines():
                        if line.startswith(
                            ("VmRSS:", "RssAnon:", "RssFile:", "RssShmem:")
                        ):
                            name, value, _ = line.split()
                            status[name[:-1]] = int(value) * 1024
                    item = (
                        time.perf_counter(),
                        status["VmRSS"],
                        status["RssAnon"],
                        status["RssFile"],
                        status["RssShmem"],
                        int((cgroup_path / "memory.current").read_text()),
                        int((cgroup_path / "memory.peak").read_text()),
                    )
                    samples.append(item)
                    log.write(json.dumps(item) + "\n")

        monitor = threading.Thread(target=sample, daemon=True)
        monitor.start()
        cpu_start = process.cpu_times()
        start = time.perf_counter()
        meta.update(status="running", baseline_rss_bytes=baseline_rss)
        output.write_text(json.dumps(meta, indent=2))
        try:
            if args.operation == "analyze":
                plan = builder.analyze_plan(source)
                output.with_suffix(".plan.txt").write_text(plan)
            else:
                meta["merge_stats"] = builder.execute(source)
            # analyze_plan currently consumes stream errors in Lance. Its return
            # is plan evidence only; successful execute runs establish completion.
            meta["status"] = "diagnostic" if args.operation == "analyze" else "ok"
        except Exception as error:
            meta.update(
                status="error", error=str(error), error_type=type(error).__name__
            )
        finally:
            meta["seconds"] = time.perf_counter() - start
            meta["source_prepare_and_merge_seconds"] = (
                meta["source_prepare_seconds"] + meta["seconds"]
            )
            cpu_end = process.cpu_times()
            meta["cpu_seconds"] = (cpu_end.user - cpu_start.user) + (
                cpu_end.system - cpu_start.system
            )
            meta["average_cpu_cores"] = meta["cpu_seconds"] / meta["seconds"]
            stop.set()
            monitor.join()
        meta["cgroup_memory_peak_bytes"] = int(
            (cgroup_path / "memory.peak").read_text()
        )
        meta["sampled_peak_anon_bytes"] = max([0] + [sample[2] for sample in samples])
        meta["sampled_peak_file_bytes"] = max([0] + [sample[3] for sample in samples])
        meta.update(
            sampled_peak_rss_bytes=max([baseline_rss] + [s[1] for s in samples]),
            process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            * 1024,
            target_rows_per_second=rows / meta["seconds"],
            source_rows_per_second=source_rows / meta["seconds"],
        )
        output.with_suffix(".rss.json").write_text(json.dumps(samples))
        # Save execution metrics before read-back validation, so a validator
        # failure cannot hide an otherwise completed measured call.
        output.write_text(json.dumps(meta, indent=2))
        if meta["status"] == "ok" and args.operation == "execute":
            stats = meta["merge_stats"]
            assert stats["num_updated_rows"] == min(source_rows, rows), stats
            assert stats["num_inserted_rows"] == (
                max(0, source_rows - rows) if args.full_schema else 0
            ), stats
            assert stats["num_deleted_rows"] == 0, stats
            assert lance.dataset(args.uri).count_rows() == max(rows, source_rows), stats
            if args.source_binary_bytes:
                updated = 0
                for batch in lance.dataset(args.uri).to_batches(
                    columns=["new_payload"], batch_size=4
                ):
                    lengths = pc.binary_length(batch.column(0))
                    updated += pc.sum(
                        pc.equal(lengths, args.source_binary_bytes)
                    ).as_py()
                assert updated == source_rows
            elif not args.full_schema:
                assert (
                    lance.dataset(args.uri).count_rows("c0 = -9505 AND c1 = -10077")
                    == source_rows
                )
            meta["validated"] = True
    output.write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta), flush=True)
    if meta.get("status") == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
