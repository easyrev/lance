"""Controlled local merge measurements; invoke through the repository's uv environment."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import threading
import time


parser = argparse.ArgumentParser()
parser.add_argument("--package", help="Directory containing the frozen lance package")
parser.add_argument("--label", default="candidate")
parser.add_argument("--root", required=True, type=Path)
parser.add_argument("--trial", default="0")
parser.add_argument("--kind", default="lance", choices=["lance", "arrow", "scanner", "oneshot", "table"])
parser.add_argument("--conflict", action="store_true")
parser.add_argument("--retries", type=int, default=3)
parser.add_argument("--prepare", action="store_true")
parser.add_argument("--keep-target", action="store_true")
parser.add_argument("--rows", type=int, default=262144)
parser.add_argument("--width", type=int, default=512)
args = parser.parse_args()
if args.package:
    sys.path.insert(0, args.package)

import lance  # noqa: E402
import lance.lance as native  # noqa: E402
import numpy as np  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.compute as pc  # noqa: E402
import pyarrow.dataset as pads  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

pa.set_cpu_count(4)
pa.set_io_thread_count(4)


def proc_io():
    return {key: int(value) for key, value in
            (line.split(":") for line in Path("/proc/self/io").read_text().splitlines())}


def source_table(rows, width):
    rng = np.random.default_rng(7895)
    buffer = pa.py_buffer(rng.integers(0, 256, rows * width, dtype=np.uint8))
    payload = pa.Array.from_buffers(pa.binary(width), rows, [None, buffer])
    return pa.table({"id": np.arange(rows, dtype=np.int64),
                     "value": np.ones(rows, dtype=np.int64), "payload": payload})


if args.prepare:
    args.root.mkdir(parents=True, exist_ok=True)
    table = source_table(args.rows, args.width)
    lance.write_dataset(table, args.root / "source.lance", max_rows_per_file=65536,
                        max_rows_per_group=4096)
    (args.root / "source.parquet").mkdir()
    for part, offset in enumerate(range(0, args.rows, 65536)):
        pq.write_table(table.slice(offset, 65536),
                       args.root / "source.parquet" / f"part-{part:03}.parquet",
                       row_group_size=4096, compression="NONE")
    target = table.slice(0, 1).set_column(1, "value", pa.array([0], type=pa.int64()))
    lance.write_dataset(target, args.root / "target-template.lance")
    (args.root / "fixture.json").write_text(json.dumps({
        "rows": args.rows, "width": args.width, "arrow_bytes": table.nbytes,
        "payload_sha256": hashlib.sha256(table["payload"].chunk(0).buffers()[1]).hexdigest(),
        "seed": 7895, "source_fragments": len(lance.dataset(args.root / "source.lance").get_fragments()),
        "pyarrow": pa.__version__, "lance": lance.__version__,
    }, indent=2) + "\n")
    print((args.root / "fixture.json").read_text())
    raise SystemExit

fixture = json.loads((args.root / "fixture.json").read_text())
trial = args.root / f"{args.label}-{args.kind}-{'conflict' if args.conflict else 'clean'}-{args.trial}"
trial.mkdir()
target_path = trial / "target.lance"
shutil.copytree(args.root / "target-template.lance", target_path)

commit_versions = []
commit_events = []
concurrent_versions = []


@contextlib.contextmanager
def lock(version):
    entered = time.perf_counter() - start
    usage = resource.getrusage(resource.RUSAGE_SELF)
    event = {"version": version, "entered_s": entered,
             "user_s": usage.ru_utime - before.ru_utime,
             "system_s": usage.ru_stime - before.ru_stime}
    commit_events.append(event)
    commit_versions.append(version)
    if args.conflict and not concurrent_versions:
        event["update_started_s"] = time.perf_counter() - start
        failures = []

        def concurrent_update():
            try:
                other = lance.dataset(target_path)
                other.update({"value": "-99"}, where="id = 0")
                concurrent_versions.append(other.version)
            except BaseException as exc:
                failures.append(exc)

        # A separate thread avoids starting a nested Tokio runtime in the lock callback.
        worker = threading.Thread(target=concurrent_update, daemon=True)
        worker.start()
        worker.join(timeout=30)
        event["update_finished_s"] = time.perf_counter() - start
        assert not worker.is_alive(), "concurrent update did not finish"
        if failures:
            raise failures[0]
    try:
        yield
    finally:
        event["released_s"] = time.perf_counter() - start


target = lance.dataset(target_path, commit_lock=lock)
if args.kind in ("lance", "oneshot", "table"):
    disk_source = lance.dataset(args.root / "source.lance")
else:
    disk_source = pads.dataset(args.root / "source.parquet", format="parquet")
source = disk_source
if args.kind == "oneshot":
    source = disk_source.to_batches(batch_size=4096)
elif args.kind == "table":
    source = disk_source.to_table()
elif args.kind == "scanner":
    source = disk_source.scanner(batch_size=4096, use_threads=False)

# explain_plan is schema-only in upstream and is not evidence of source routing.
plan_builder = target.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().conflict_retries(args.retries)
if args.kind != "oneshot":
    (trial / "schema-only-plan.txt").write_text(plan_builder.explain_plan(disk_source.schema))

builder = target.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().conflict_retries(args.retries)
source_path = args.root / ("source.lance" if args.kind in ("lance", "oneshot", "table") else "source.parquet")
for source_file in sorted(source_path.rglob("*")):
    if source_file.is_file():
        with source_file.open("rb") as handle:
            while handle.read(1024 * 1024):
                pass
probe_log = Path(os.environ["REPLAY_PROBE_LOG"])
probe_log.write_text("")
before = resource.getrusage(resource.RUSAGE_SELF)
io_before = proc_io()
wall_start_ns = time.time_ns()
start = time.perf_counter()
error = None
stats = None
try:
    stats = builder.execute(
        source, schema=disk_source.schema if args.kind == "oneshot" else None
    )
except Exception as exc:
    error = {"type": type(exc).__name__, "message": str(exc)}
elapsed = time.perf_counter() - start
wall_end_ns = time.time_ns()
after = resource.getrusage(resource.RUSAGE_SELF)
io_after = proc_io()
events = [line.split("\t") for line in probe_log.read_text().splitlines()]

latest = lance.dataset(target_path)
actual = latest.to_table(columns=["id", "value"])
payload_sha256 = None
expected_rows = fixture["rows"] if error is None else 1
assert actual.num_rows == expected_rows, (actual.num_rows, expected_rows)
if error is None:
    assert actual["value"].null_count == 0
    assert pc.all(pc.equal(actual["value"], 1)).as_py()
    assert pc.count_distinct(actual["id"]).as_py() == fixture["rows"]
    assert pc.min(actual["id"]).as_py() == 0
    assert pc.max(actual["id"]).as_py() == fixture["rows"] - 1
    payloads = latest.to_table(columns=["id", "payload"]).sort_by("id")["payload"]
    digest = hashlib.sha256()
    for chunk in payloads.chunks:
        width = fixture["width"]
        digest.update(memoryview(chunk.buffers()[1])[chunk.offset * width:(chunk.offset + len(chunk)) * width])
    payload_sha256 = digest.hexdigest()
    assert payload_sha256 == fixture["payload_sha256"]
    assert latest.version == (3 if args.conflict else 2), latest.version
    assert stats == {"num_inserted_rows": fixture["rows"] - 1,
                     "num_updated_rows": 1, "num_deleted_rows": 0}, stats
    assert commit_versions == ([2, 3] if args.conflict else [2]), commit_versions
    if args.conflict:
        assert concurrent_versions == [2], concurrent_versions
else:
    assert args.conflict and args.retries == 0, error
    assert latest.version == 2
    assert actual["value"].to_pylist() == [-99]
    assert commit_versions == [2], commit_versions

replay_dirs = [event[1] for event in events if event[0] == "mkdir" and Path(event[1]).name.startswith(".tmp")]
spill_files = [event for event in events if event[0] == "unlink" and event[1].endswith("spill.arrows")]
result = {
    "label": args.label, "kind": args.kind, "trial": args.trial,
    "conflict": args.conflict, "retries": args.retries, "elapsed_s": elapsed,
    "wall_start_ns": wall_start_ns, "wall_end_ns": wall_end_ns,
    "user_s": after.ru_utime - before.ru_utime,
    "system_s": after.ru_stime - before.ru_stime,
    "cpu_s": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
    "first_commit_elapsed_s": commit_events[0]["entered_s"],
    "first_commit_cpu_s": commit_events[0]["user_s"] + commit_events[0]["system_s"],
    "concurrent_update_elapsed_s": sum(event.get("update_finished_s", 0) - event.get("update_started_s", 0)
                                       for event in commit_events),
    "commit_events": commit_events,
    "max_rss_kib": after.ru_maxrss,
    "io_delta": {key: io_after[key] - io_before[key] for key in io_before},
    "replay_directory_count": len(replay_dirs),
    "spill_file_count": len(spill_files),
    "spill_file_unlink_bytes": sum(int(event[2]) for event in spill_files),
    "commit_versions": commit_versions, "concurrent_versions": concurrent_versions,
    "final_version": latest.version, "final_rows": actual.num_rows,
    "stats": stats, "error": error, "correct": True,
    "payload_sha256": payload_sha256,
    "python": sys.version, "pyarrow": pa.__version__, "lance": lance.__version__,
    "package": lance.__file__, "extension": native.__file__,
    "extension_sha256": hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),
    "source_sha256": {name: hashlib.sha256((Path(lance.__file__).parent / name).read_bytes()).hexdigest()
                      for name in ("__init__.py", "types.py", "dataset.py")},
    "probe_sha256": hashlib.sha256(Path(os.environ["LD_PRELOAD"]).read_bytes()).hexdigest() if os.environ.get("LD_PRELOAD") else None,
    "thread_limits": {name: os.environ.get(name) for name in
                      ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "RAYON_NUM_THREADS", "TOKIO_WORKER_THREADS")},
    "arrow_cpu_count": pa.cpu_count(), "arrow_io_thread_count": pa.io_thread_count(),
    "fixture": fixture,
    "cache": "source files explicitly read before timing to warm OS page cache; target fixture copied before timing; no eviction",
}
(trial / "result.json").write_text(json.dumps(result, indent=2) + "\n")
if not args.keep_target:
    shutil.rmtree(target_path)
print(json.dumps(result))
