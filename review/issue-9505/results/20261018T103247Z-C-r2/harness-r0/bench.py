"""Frozen #9505 worker and coordinator. Invoke through a checkout's uv environment."""

import argparse
import hashlib
import json
import os
import resource
import subprocess
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECKOUTS = Path("/mnt/lance/checkouts")
CGROUP_ROOT = Path("/sys/fs/cgroup/lance9505-validation")
GIB = 1 << 30
MIB = 1 << 20


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def append(path, value):
    value = {"wall_ns": time.time_ns()} | value
    with Path(path).open("a", buffering=1) as output:
        output.write(json.dumps(value) + "\n")


def workload(name):
    common = dict(
        seed=9505,
        epoch=1,
        source_rows=100,
        batch_rows=32768,
        source="reader",
        full=False,
        binary=0,
        dense=False,
        first_seen=False,
    )
    choices = {
        "tiny": dict(rows=64, columns=8, fragment_rows=16, source_rows=4),
        "F4": dict(rows=4_000_000, columns=44, fragment_rows=100_000),
        "F16": dict(rows=16_000_000, columns=44, fragment_rows=100_000),
        "R": dict(
            rows=100_000,
            columns=44,
            fragment_rows=25_000,
            source_rows=3_000_000,
            full=True,
        ),
        "Wn": dict(
            rows=400, columns=3, fragment_rows=25, binary=5 * MIB, source_rows=25
        ),
        "Ws": dict(
            rows=400,
            columns=3,
            fragment_rows=25,
            binary=5 * MIB,
            source_rows=25,
            source_binary=10 * MIB,
        ),
        "Wauto": dict(
            rows=200,
            columns=3,
            fragment_rows=25,
            binary=5 * MIB,
            source_rows=25,
            source_binary=10 * MIB,
        ),
        "V_sparse": dict(
            rows=2_000_000,
            columns=3,
            fragment_rows=100_000,
            binary=2048,
            variable=True,
            fixture_name="V_sparse_r2",
            payload_length="splitmix64-per-row-separate-domain-v2",
            source_rows=25,
        ),
        "W_dense": dict(
            rows=400,
            columns=3,
            fragment_rows=25,
            binary=5 * MIB,
            dense=True,
            source_rows=25,
        ),
    }
    return common | choices[name] | dict(name=name, oracle="splitmix64-v1")


def schema(spec, source=False):
    import pyarrow as pa

    if source and not spec["full"]:
        names = (
            ["id", "new_payload"] if spec.get("source_binary") else ["id", "c0", "c1"]
        )
    else:
        names = ["id"] + [f"c{i}" for i in range(spec["columns"] - 1)]
        if spec["binary"]:
            names += ["payload", "new_payload", "row_marker"]
    return pa.schema(
        [
            (
                name,
                pa.large_binary() if name in ("payload", "new_payload") else pa.int64(),
            )
            for name in names
        ]
    )


def values(ids, column, epoch=0):
    import numpy as np

    x = ids.astype(np.uint64) ^ np.uint64(9505 + column * 104729)
    with np.errstate(over="ignore"):
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    x ^= x >> np.uint64(31)
    return (x & np.uint64((1 << 40) - 1)).astype(np.int64) + epoch * (1 << 42)


def payload(marker, size, epoch=0):
    import numpy as np

    return np.random.default_rng(9505 + int(marker) * 17 + epoch * 10077).bytes(size)


def payload_size(marker, spec):
    if not spec.get("variable"):
        return spec["binary"]
    # Keep length independent of the content RNG and the join-key selection.
    bits = (1 << 64) - 1
    value = int(marker) ^ (9505 + 99 * 104729)
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & bits
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & bits
    value ^= value >> 31
    return 128 + value % (2048 - 128 + 1)


def keys_for(spec):
    import numpy as np

    if spec["full"]:
        return None
    if spec["dense"] or spec.get("hot_keys"):
        return np.arange(spec["source_rows"], dtype=np.int64)
    keys = np.linspace(0, spec["rows"] - 1, spec["source_rows"], dtype=np.int64)
    # Nonmonotonic source order exercises gathering across fragments.
    return np.random.default_rng(9505).permutation(keys)


def target_batches(spec):
    import numpy as np
    import pyarrow as pa

    row_batch = min(
        spec["batch_rows"], 4 if spec["binary"] >= MIB else spec["batch_rows"]
    )
    end = spec.get("target_end", spec["rows"])
    for start in range(spec.get("target_start", 0), end, row_batch):
        marker = np.arange(start, min(start + row_batch, end), dtype=np.int64)
        ids = (
            np.where(marker < spec["rows"] * 9 // 10, marker % 5, marker + 100)
            if spec["dense"]
            else marker
        )
        columns = {"id": pa.array(ids)}
        columns |= {
            f"c{i}": pa.array(values(marker, i)) for i in range(spec["columns"] - 1)
        }
        if spec["binary"]:
            columns |= {
                "payload": pa.array(
                    [payload(row, payload_size(row, spec)) for row in marker],
                    type=pa.large_binary(),
                ),
                "new_payload": pa.array([b""] * len(marker), type=pa.large_binary()),
                "row_marker": pa.array(marker),
            }
        yield pa.RecordBatch.from_pydict(columns, schema=schema(spec))


def source_batches(spec, directory):
    import numpy as np
    import pyarrow as pa

    keys = keys_for(spec)
    count = spec["source_rows"]
    for number in range(spec.get("zero_batches", 0)):
        batch = pa.RecordBatch.from_arrays([pa.array([], type=field.type) for field in schema(spec, source=True)], schema=schema(spec, source=True))
        append(directory / "producer.jsonl", dict(event="ready", t=time.monotonic(), batch=number, rows=0, bytes=0))
        yield batch
    copies = 2 if spec["first_seen"] else 1
    for copy in range(copies):
        for number, start in enumerate(range(0, count, spec["batch_rows"])):
            append(
                directory / "producer.jsonl",
                dict(event="next", t=time.monotonic(), batch=number, copy=copy),
            )
            delay = spec.get("delays", {}).get(str(number), 0)
            if delay:
                time.sleep(delay)
            if spec.get("pending_after") == number:
                append(
                    directory / "producer.jsonl",
                    dict(event="pending", t=time.monotonic()),
                )
                while True:
                    time.sleep(1)
            ids = (
                np.arange(start, min(start + spec["batch_rows"], count), dtype=np.int64)
                if spec["full"]
                else keys[start : start + spec["batch_rows"]]
            )
            if spec["full"]:
                columns = {"id": pa.array(ids)} | {
                    f"c{i}": pa.array(values(ids, i, spec["epoch"]))
                    for i in range(spec["columns"] - 1)
                }
            elif spec.get("source_binary"):
                columns = {
                    "id": pa.array(ids),
                    "new_payload": pa.array(
                        [payload(row, spec["source_binary"], 1) for row in ids],
                        type=pa.large_binary(),
                    ),
                }
            else:
                columns = {
                    "id": pa.array(ids),
                    "c0": pa.array(
                        np.full(
                            len(ids), -9505 if copy == 0 else -12345, dtype=np.int64
                        )
                    ),
                    "c1": pa.array(np.full(len(ids), -10077, dtype=np.int64)),
                }
            batch = pa.RecordBatch.from_pydict(
                columns, schema=schema(spec, source=True)
            )
            append(
                directory / "producer.jsonl",
                dict(
                    event="ready",
                    t=time.monotonic(),
                    batch=number,
                    rows=batch.num_rows,
                    bytes=batch.nbytes,
                    copy=copy,
                ),
            )
            yield batch
    append(directory / "producer.jsonl", dict(event="eof", t=time.monotonic()))


def fixture(spec):
    import lance
    import pyarrow as pa

    uri = ROOT / "fixtures" / spec.get("fixture_name", spec["name"])
    if uri.exists():
        metadata = json.loads((uri / "fixture.json").read_text())
        assert metadata["spec"] == spec, (metadata["spec"], spec)
        return
    boundaries = spec.get("fragment_boundaries", [0, spec["rows"]])
    for start, end in zip(boundaries, boundaries[1:]):
        portion = spec | dict(target_start=start, target_end=end)
        ds = lance.write_dataset(
            pa.RecordBatchReader.from_batches(schema(spec), target_batches(portion)),
            str(uri),
            mode="create" if start == 0 else "append",
            data_storage_version="2.2",
            max_rows_per_file=(end - start) if spec.get("fragment_boundaries") else spec["fragment_rows"],
            max_rows_per_group=spec["batch_rows"],
        )
    files = sorted(
        {
            str(uri / "data" / file.path)
            for fragment in ds.get_fragments()
            for file in fragment.data_files()
        }
    )
    save(
        uri / "fixture.json",
        dict(
            spec=spec,
            version=ds.version,
            rows=ds.count_rows(),
            fragments=len(ds.get_fragments()),
            files=files,
        ),
    )


def execute(spec, directory):
    import lance
    import pyarrow as pa

    directory.mkdir(parents=True, exist_ok=True)
    uri = ROOT / "fixtures" / spec.get("fixture_name", spec["name"])
    ds = lance.dataset(str(uri))
    initial = json.loads((uri / "fixture.json").read_text())["version"]
    if ds.version != initial:
        ds.checkout_version(initial).restore()
        ds = lance.dataset(str(uri))
    result = dict(
        status="started",
        validated=False,
        pid=os.getpid(),
        spec=spec,
        module=lance.__file__,
        version=lance.__version__,
        snapshot=ds.version,
        baseline_rss_bytes=rss(os.getpid()).get("VmRSS", 0),
    )
    reader = pa.RecordBatchReader.from_batches(
        schema(spec, source=True), source_batches(spec, directory)
    )
    started = time.perf_counter()
    source = reader.read_all() if spec["source"] == "materialized" else reader
    result["input_materialization_seconds"] = time.perf_counter() - started
    builder = (
        ds.merge_insert("id")
        .when_matched_update_all()
        .use_index(False)
        .write_mode("rewrite_rows")
        .conflict_retries(0)
    )
    if spec["full"]:
        builder = builder.when_not_matched_insert_all()
    if spec["first_seen"]:
        raise ValueError("Python has no FirstSeen setter; use the pinned Rust test through first-seen.py")
    result["stage"] = "execute"
    result["source_lazy_at_execute_start"] = not (directory / "producer.jsonl").exists()
    result["execute_started_monotonic"] = time.monotonic()
    result["execute_started_wall_ns"] = time.time_ns()
    save(directory / "metrics.json", result)
    cpu_start = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter()
    try:
        result["merge_stats"] = builder.execute(source)
        result.update(status="execute_returned", execute_returned=True)
    except Exception as error:
        message = str(error)
        status = (
            "resource_exhausted"
            if any(
                word in message.lower()
                for word in (
                    "resources exhausted",
                    "resource exhausted",
                    "failed to allocate",
                )
            )
            else "source_error"
            if "source-test-failure" in message
            else "execution_error"
        )
        result.update(status=status, error=message, traceback=traceback.format_exc())
    result["merge_seconds"] = time.perf_counter() - started
    cpu_end = resource.getrusage(resource.RUSAGE_SELF)
    result["cpu_seconds"] = (
        cpu_end.ru_utime + cpu_end.ru_stime - cpu_start.ru_utime - cpu_start.ru_stime
    )
    result["average_cpu_cores"] = result["cpu_seconds"] / result["merge_seconds"]
    result["ru_maxrss_bytes"] = cpu_end.ru_maxrss * 1024
    result["stage"] = "execute_finished"
    save(directory / "metrics.json", result)
    append(
        directory / "stages.jsonl", dict(stage="execute_finished", t=time.monotonic())
    )


def pool_diagnostic(directory):
    import lance
    import pyarrow as pa

    spec = json.loads((directory / "spec.json").read_text())
    small = spec.get("small", False)
    target = pa.table({"id": pa.array([1], type=pa.int8()), "old": ["unchanged"]})
    ds = lance.write_dataset(
        target, str(directory / "dataset"), data_storage_version="2.2"
    )
    source = (pa.table({"id": pa.array([1], type=pa.int8()), "old": ["changed"]})
              if small else pa.table({"id": pa.array([0] * 100000, type=pa.int8())}))
    metrics = dict(
        status="started",
        snapshot=ds.version,
        rows=1,
        source_rows=len(source),
        source="materialized",
        execute_returned=False,
        purpose="small matched source" if small else "known build exceeds pool; no matches",
    )
    save(directory / "metrics.json", metrics)
    started = time.perf_counter()
    try:
        metrics["merge_stats"] = (
            ds.merge_insert("id")
            .when_matched_update_all()
            .use_index(False)
            .conflict_retries(0)
            .execute(source)
        )
        metrics.update(status="execute_returned", execute_returned=True)
    except Exception as error:
        metrics.update(
            status="resource_exhausted"
            if "exhausted" in str(error).lower()
            or "failed to allocate" in str(error).lower()
            else "execution_error",
            error=str(error),
        )
    metrics["merge_seconds"] = time.perf_counter() - started
    save(directory / "metrics.json", metrics)


def validate_pool(directory):
    import lance
    import pyarrow as pa

    metrics = json.loads((directory / "metrics.json").read_text())
    ds = lance.dataset(str(directory / "dataset"))
    small = json.loads((directory / "spec.json").read_text()).get("small", False)
    expected = pa.table({"id": pa.array([1], type=pa.int8()), "old": ["changed" if small and metrics["execute_returned"] else "unchanged"]})
    assert ds.to_table().equals(expected)
    if not metrics["execute_returned"]:
        assert ds.version == metrics["snapshot"]
    save(
        directory / "validation.json",
        dict(
            validated=True,
            rows=1,
            expected_no_updates=not small,
            no_failed_commit=not metrics["execute_returned"],
        ),
    )


def validate(spec, directory):
    import lance
    import numpy as np

    ds = lance.dataset(str(ROOT / "fixtures" / spec.get("fixture_name", spec["name"])))
    metrics = json.loads((directory / "metrics.json").read_text())
    count = 0
    updated = 0
    hashes = {name: hashlib.sha256() for name in ds.schema.names}
    keys = keys_for(spec)
    keys = np.sort(keys) if keys is not None else None
    expected_rows = (
        max(spec["rows"], spec["source_rows"]) if spec["full"] else spec["rows"]
    )
    seen = np.zeros(expected_rows, dtype=np.bool_)
    marker_sum = 0
    marker_square_sum = 0
    for batch in ds.to_batches(
        batch_size=4 if spec["binary"] >= MIB else 32768, batch_readahead=1
    ):
        ids = batch["id"].to_numpy()
        marker = batch["row_marker"].to_numpy() if spec["binary"] else ids
        assert np.all((marker >= 0) & (marker < expected_rows))
        assert len(np.unique(marker)) == len(marker)
        assert not np.any(seen[marker])
        seen[marker] = True
        expected_ids = (
            np.where(marker < spec["rows"] * 9 // 10, marker % 5, marker + 100)
            if spec["dense"]
            else marker
        )
        assert np.array_equal(ids, expected_ids)
        if spec["full"]:
            hit = ids < spec["source_rows"]
        else:
            hit = np.isin(ids, keys)
        updated += int(np.count_nonzero(hit & (marker < spec["rows"])))
        for name in batch.schema.names:
            array = batch[name]
            if name.startswith("c"):
                number = int(name[1:])
                expected = values(marker, number)
                if spec["full"]:
                    expected = np.where(
                        hit, values(ids, number, spec["epoch"]), expected
                    )
                elif not spec.get("source_binary") and number < 2:
                    expected = np.where(hit, -9505 if number == 0 else -10077, expected)
                actual = array.to_numpy()
                assert np.array_equal(actual, expected), (
                    name,
                    ids[np.flatnonzero(actual != expected)[:10]],
                )
                hashes[name].update(actual.tobytes())
            elif name in ("payload", "new_payload"):
                for index, row in enumerate(marker):
                    actual = array[index].as_py()
                    expected = (
                        payload(row, payload_size(row, spec))
                        if name == "payload"
                        else payload(ids[index], spec["source_binary"], 1)
                        if spec.get("source_binary") and hit[index]
                        else b""
                    )
                    assert (
                        hashlib.sha256(actual).digest()
                        == hashlib.sha256(expected).digest()
                    ), (name, int(row))
                    hashes[name].update(actual)
            else:
                hashes[name].update(array.to_numpy().tobytes())
        count += len(ids)
        marker_sum += sum(map(int, marker))
        marker_square_sum += sum(int(x) ** 2 for x in marker)
    assert count == expected_rows, (count, expected_rows)
    assert marker_sum == expected_rows * (expected_rows - 1) // 2
    assert (
        marker_square_sum
        == expected_rows * (expected_rows - 1) * (2 * expected_rows - 1) // 6
    )
    expected_updated = (
        min(spec["rows"], spec["source_rows"])
        if spec["full"]
        else spec["rows"] * 9 // 10
        if spec["dense"]
        else spec["source_rows"]
    )
    stats = metrics["merge_stats"]
    assert updated == expected_updated, (updated, expected_updated)
    assert stats["num_updated_rows"] == expected_updated, stats
    assert stats["num_deleted_rows"] == 0, stats
    assert stats["num_inserted_rows"] == expected_rows - spec["rows"], stats
    assert ds.version > metrics["snapshot"]
    save(
        directory / "validation.json",
        dict(
            validated=True,
            rows=count,
            updated=updated,
            inserted=expected_rows - spec["rows"],
            deleted=0,
            hashes={name: value.hexdigest() for name, value in hashes.items()},
            oracle="splitmix64-v1-all-fields",
            values_changed=True,
            version=ds.version,
        ),
    )


def validate_cancel(spec, directory):
    import lance
    import pyarrow as pa
    metrics = json.loads((directory / "metrics.json").read_text())
    ds = lance.dataset(str(ROOT / "fixtures" / spec.get("fixture_name", spec["name"])))
    assert ds.version == metrics["snapshot"]
    expected = pa.Table.from_batches(list(target_batches(spec)))
    assert ds.to_table().equals(expected)
    save(directory / "cancellation-validation.json", dict(no_commit=True, unchanged=True, version=ds.version))


def rss(pid):
    try:
        result = {}
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "RssAnon:", "RssFile:", "RssShmem:")):
                key, value, _ = line.split()
                result[key.rstrip(":")] = int(value) * 1024
        return result
    except FileNotFoundError:
        return {}


def controls(path):
    result = {}
    for name in [
        "memory.max",
        "memory.swap.max",
        "memory.current",
        "memory.peak",
        "memory.events",
        "cpu.max",
        "cpu.stat",
    ]:
        control = path / name
        result[name] = control.read_text().strip() if control.exists() else None
    return result


def isolated(
    operation, variant, spec, directory, limit, pool, timeout=600, diagnostics=False,
    command_override=None,
):
    group = CGROUP_ROOT / f"{directory.name}-{operation}"
    group.mkdir()
    (group / "memory.max").write_text(str(limit))
    (group / "memory.swap.max").write_text("0")
    (group / "memory.oom.group").write_text("1")
    before = controls(group)
    environment = os.environ.copy()
    environment["LANCE_MEM_POOL_SIZE"] = str(pool)
    environment.pop("LANCE_BYPASS_SPILLING", None)
    environment.pop("LANCE_MERGE_DIAGNOSTICS", None)
    if diagnostics:
        environment["LANCE_MERGE_DIAGNOSTICS"] = "1"
    environment["LANCE_MERGE_EVIDENCE"] = str(directory / "candidate.jsonl")
    if variant.startswith("C"):
        environment["LANCE_MERGE_EXPERIMENT"] = variant
    checkout = (
        "C"
        if variant.startswith("C")
        else "P"
        if variant == "P_reconstructed"
        else variant
    )
    command = [
        "/root/.local/bin/uv",
        "run",
        "--no-sync",
        "python",
        str(Path(__file__).resolve()),
        "worker",
        operation,
        str(directory),
    ]
    if command_override is not None:
        command = command_override
    if diagnostics and spec.get("strace"):
        command = ["strace", "-ff", "-ttt", "-yy", "-e", "trace=read,pread64,write,openat", "-o", str(directory / "io.trace")] + command

    def enter():
        os.setsid()
        (group / "cgroup.procs").write_text(str(os.getpid()))

    directory.mkdir(parents=True, exist_ok=True)
    save(directory / "spec.json", spec)
    started = time.monotonic()
    cancelled = False
    with (
        (directory / f"{operation}.log").open("w") as log,
        (directory / f"{operation}-memory.jsonl").open("w", buffering=1) as memory,
    ):
        process = subprocess.Popen(
            command,
            cwd=CHECKOUTS / checkout / "python",
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            preexec_fn=enter,
        )
        while process.poll() is None:
            members = [int(pid) for pid in (group / "cgroup.procs").read_text().split()]
            observations = [(pid, rss(pid)) for pid in members]
            worker_pid, observed = max(
                observations,
                key=lambda entry: entry[1].get("VmRSS", 0),
                default=(process.pid, {}),
            )
            sample = dict(t=time.monotonic(), pid=worker_pid, **observed)
            sample.update(
                cgroup_current=int((group / "memory.current").read_text()),
                cgroup_peak=int((group / "memory.peak").read_text()),
            )
            memory.write(json.dumps(sample) + "\n")
            if sample["t"] - started > timeout:
                cancelled = True
                (group / "cgroup.kill").write_text("1")
            time.sleep(0.01)
    after = controls(group)
    events = dict(line.split() for line in after["memory.events"].splitlines())
    result = dict(
        command=command,
        variant=variant,
        operation=operation,
        exit_code=process.returncode,
        timeout=cancelled,
        before=before,
        after=after,
        confirmed_oom=int(events["oom_kill"]) > 0,
    )
    save(directory / f"{operation}-resource-events.json", result)
    group.rmdir()
    return result


def run(
    variant, spec, run_id, block=0, limit=8 * GIB, pool=GIB, timeout=600, formal=False
):
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            command_name = Path("/proc", entry, "comm").read_text().strip()
        except (FileNotFoundError, ProcessLookupError):
            continue
        if command_name in ("cargo", "rustc"):
            raise RuntimeError("Compilation is active. Measurements must wait.")
    directory = ROOT / "runs" / run_id
    if directory.exists():
        raise RuntimeError(f"Refusing to overwrite {directory}")
    plan = dict(
        run_id=run_id,
        block=block,
        variant=variant,
        workload=spec["name"],
        spec=spec,
        pool_bytes=pool,
        memory_max_bytes=limit,
        swap_max_bytes=0,
        cache="hot",
        formal=formal,
        status="planned",
    )
    append(ROOT / "run-manifest.jsonl", plan)
    metadata = json.loads(
        (ROOT / "fixtures" / spec.get("fixture_name", spec["name"]) / "fixture.json").read_text()
    )
    for name in metadata["files"]:
        with open(name, "rb") as file:
            while file.read(8 * MIB):
                pass
    directory.mkdir(parents=True)
    save(directory / "warm-files.json", metadata["files"])
    execution = isolated(
        "execute",
        variant,
        spec,
        directory,
        limit,
        pool,
        timeout,
        diagnostics=not formal,
    )
    for alias, target in (("execution.log", "execute.log"), ("memory.jsonl", "execute-memory.jsonl"), ("resource-events.json", "execute-resource-events.json")):
        (directory / alias).symlink_to(target)
    metric_path = directory / "metrics.json"
    metrics = json.loads(metric_path.read_text()) if metric_path.exists() else {}
    if execution["confirmed_oom"]:
        status = "confirmed_oom"
    elif execution["timeout"]:
        status = "timeout/cancelled"
    elif metrics.get("execute_returned") and execution["exit_code"] == 0:
        validation = isolated("validate", "U", spec, directory, 8 * GIB, pool)
        status = (
            "validated_success"
            if validation["exit_code"] == 0 and (directory / "validation.json").exists()
            else "validation_error"
        )
    else:
        status = metrics.get("status", "infrastructure_error")
        if status == "started" or metrics.get("execute_returned"):
            status = "infrastructure_error"
    metrics.update(
        status=status,
        validated=status == "validated_success",
        execution=execution,
        run_id=run_id,
        variant=variant,
        block=block,
        formal=formal,
    )
    evidence_path = directory / "candidate.jsonl"
    if evidence_path.exists():
        evidence = [json.loads(line) for line in evidence_path.read_text().splitlines()]
        for phase in ("resources", "source_prepared", "execute_complete", "join_policy"):
            selected = [event for event in evidence if event.get("phase") == phase]
            if selected:
                metrics[phase] = selected[-1]
    samples = [json.loads(line) for line in (directory / "execute-memory.jsonl").read_text().splitlines()]
    metrics["sampled_peak_rss_bytes"] = max((sample.get("VmRSS", 0) for sample in samples), default=0)
    metrics["sampled_peak_anon_bytes"] = max((sample.get("RssAnon", 0) for sample in samples), default=0)
    metrics["detailed_diagnostics_enabled"] = not formal
    save(metric_path, metrics)
    append(
        ROOT / "run-manifest.jsonl",
        plan | dict(status=status, seconds=metrics.get("merge_seconds")),
    )
    print(
        json.dumps(
            dict(run_id=run_id, status=status, seconds=metrics.get("merge_seconds"))
        ),
        flush=True,
    )
    return status


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    worker = sub.add_parser("worker")
    worker.add_argument(
        "operation", choices=["execute", "validate", "pool", "validate_pool", "validate_cancel"]
    )
    worker.add_argument("directory", type=Path)
    generate = sub.add_parser("generate")
    generate.add_argument("names", nargs="+")
    single = sub.add_parser("run")
    single.add_argument("variant")
    single.add_argument("workload")
    single.add_argument("run_id")
    single.add_argument("--pool", type=int, default=GIB)
    single.add_argument("--limit", type=int, default=8 * GIB)
    single.add_argument("--block", type=int, default=0)
    single.add_argument("--formal", action="store_true")
    args = parser.parse_args()
    if args.action == "generate":
        specs = [workload(name) for name in args.names]
        for spec in specs:
            fixture(spec)
        save(ROOT / "workloads.json", specs)
    elif args.action == "worker":
        spec = json.loads((args.directory / "spec.json").read_text())
        if args.operation == "execute":
            execute(spec, args.directory)
        elif args.operation == "pool":
            pool_diagnostic(args.directory)
        elif args.operation == "validate_pool":
            validate_pool(args.directory)
        elif args.operation == "validate_cancel":
            validate_cancel(spec, args.directory)
        else:
            validate(spec, args.directory)
    else:
        run(
            args.variant,
            workload(args.workload),
            args.run_id,
            args.block,
            args.limit,
            args.pool,
            formal=args.formal,
        )


if __name__ == "__main__":
    main()
