"""Sequential, identity-frozen merge experiments with independent value oracles."""

import argparse
import ctypes
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import platform
import random
import resource
import shutil
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path

import fixtures

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GIB = 1 << 30
CODE_FILES = ("harness.py", "fixtures.py", "legacy_fixtures.py", "RUNBOOK.md")


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def append(path, value):
    with Path(path).open("a", buffering=1) as output:
        output.write(json.dumps(dict(wall_ns=time.time_ns()) | value) + "\n")


def config():
    return read(ROOT / "config.json")


def builds():
    names = subprocess.check_output(["ps", "-eo", "comm="], text=True).splitlines()
    return [name for name in names if Path(name.strip()).name in ("cargo", "rustc", "maturin")]


def no_builds():
    active = builds()
    if active:
        raise RuntimeError(f"Compilation is active: {active}")


def environment(variant, pool):
    values = os.environ.copy()
    for name in list(values):
        if name.startswith("LANCE_MERGE_") or name in (
                "LANCE_BYPASS_SPILLING", "LANCE_MEM_POOL_SIZE", "PYTHONPATH", "PYTHONHOME"):
            values.pop(name)
    values.update(config()["variants"][variant].get("environment", {}))
    values["LANCE_MEM_POOL_SIZE"] = str(pool)
    return values


def command(variant, *arguments):
    cfg = config()
    return ([cfg["uv"], "run", "--no-sync", "python", str(HERE / "harness.py"),
             "--root", str(ROOT), *arguments], Path(cfg["variants"][variant]["checkout"]) / "python")


def identity():
    import lance
    import pyarrow

    extension = Path(importlib.util.find_spec("lance.lance").origin).resolve()
    return dict(module=str(Path(lance.__file__).resolve()), extension=str(extension),
                extension_sha256=digest(extension), version=lance.__version__,
                python=sys.version, pyarrow=pyarrow.__version__)


def tree_identity(checkout):
    def git(*args):
        return subprocess.check_output(["git", "--no-optional-locks", "-C", str(checkout), *args])

    names = set(git("ls-files", "-z").decode().split("\0"))
    names |= set(git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0"))
    names = sorted(name for name in names if name and (
        name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "python/Makefile") or
        (name.startswith(("rust/", "python/", ".cargo/")) and
         Path(name).suffix in (".rs", ".py", ".toml", ".lock", ".mk"))))
    return dict(head=git("rev-parse", "HEAD").decode().strip(),
                tracked_status=git("status", "--porcelain", "--untracked-files=no").decode(),
                diff_sha256=hashlib.sha256(git("diff", "HEAD", "--binary")).hexdigest(),
                source_hashes={name: digest(checkout / name) for name in names if (checkout / name).is_file()})


def content_identity(value):
    imported = {key: item for key, item in value["imported"].items() if key not in ("module", "extension")}
    return dict(source_hashes=value["tree"]["source_hashes"], imported=imported)


def current_freeze(labels):
    cfg = config()
    identities = {}
    for label in labels:
        variant = cfg["variants"][label]
        checkout = Path(variant["checkout"])
        subprocess.check_call(["git", "--no-optional-locks", "-C", str(checkout),
                               "merge-base", "--is-ancestor", cfg["base_commit"], "HEAD"])
        cmd, cwd = command(label, "identity")
        observed = json.loads(subprocess.check_output(cmd, cwd=cwd, env=environment(label, GIB), text=True))
        assert Path(observed["module"]).is_relative_to(checkout.resolve()), observed
        assert Path(observed["extension"]).is_relative_to(checkout.resolve()), observed
        assert variant["pool_policy"] and variant["pool_source_files"], label
        identities[label] = dict(tree=tree_identity(checkout), imported=observed,
            pool_policy=dict(source_review=variant["pool_policy"],
                source_hashes={name: digest(checkout / name) for name in variant["pool_source_files"]},
                runtime_reservation_observation="Not available unless captured separately in execution logs"))
    selected = {key: value for key, value in cfg.items() if key != "variants"}
    selected["variants"] = {label: cfg["variants"][label] for label in labels}
    return dict(labels=labels, config=selected, identities=identities, workloads=fixtures.workloads(),
                harness={name: digest(HERE / name) for name in CODE_FILES},
                build_logs={label: dict(path=cfg["variants"][label]["build_log"],
                    sha256=digest(cfg["variants"][label]["build_log"])) for label in labels},
                process_environment={name: os.environ.get(name) for name in (
                    "RUSTFLAGS", "CARGO_BUILD_TARGET", "LANCE_CPU_THREADS", "LANCE_IO_THREADS",
                    "LANCE_DEFAULT_IO_BUFFER_SIZE", "RUST_LOG")},
                host=dict(platform=platform.platform(), machine=platform.machine(), cpu_count=os.cpu_count()))


def verify_freeze(name):
    expected = read(ROOT / "freezes" / f"{name}.json")
    assert current_freeze(expected["labels"]) == expected, f"Freeze changed: {name}"
    return expected


def clone_dataset(source, destination):
    def copy(src, dst):
        if Path(src).suffix == ".lance":
            os.link(src, dst)
            return dst
        return shutil.copy2(src, dst)

    shutil.copytree(source, destination, copy_function=copy)


def fixture_manifest(name):
    return read(ROOT / "fixture-manifests" / f"{name}.json")


def verify_fixture(name, expected=None):
    manifest = fixture_manifest(name)
    if expected is not None:
        assert manifest == expected, f"Fixture identity changed: {name}"
    folder = ROOT / "fixtures" / name
    actual = {str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()}
    assert actual == set(manifest["files"]), f"Fixture file set changed: {name}"
    for relative, sha in manifest["files"].items():
        assert digest(folder / relative) == sha, f"Fixture hash changed: {name}/{relative}"
    assert read(folder / "fixture.json") == manifest["metadata"]
    assert manifest["metadata"]["spec"] == fixtures.workloads()[name]
    return manifest


def register_fixture(name, origin):
    folder = ROOT / "fixtures" / name
    destination = ROOT / "fixture-manifests" / f"{name}.json"
    if destination.exists():
        raise FileExistsError(destination)
    metadata = read(folder / "fixture.json")
    spec = fixtures.workloads()[name]
    assert metadata["spec"] == spec and metadata["rows"] == spec["rows"] and metadata["version"] == 1
    assert metadata["fragments"] == (spec["rows"] + spec["fragment_rows"] - 1) // spec["fragment_rows"]
    value = dict(metadata=metadata, origin=origin,
                 files={str(path.relative_to(folder)): digest(path)
                        for path in sorted(folder.rglob("*")) if path.is_file()})
    save(destination, value)
    return value


def import_fixtures(source_root, names):
    source_root = source_root.resolve()
    frozen = read(source_root / "freeze.json")
    manifest_path = source_root / "fixture-hashes.json"
    manifest = read(manifest_path)
    source_generator = source_root / "fixtures.py"
    assert digest(source_generator) == frozen["harness"]["fixtures.py"], "Historical generator changed"
    (ROOT / "fixtures").mkdir(exist_ok=True)
    for name in names:
        assert frozen["workloads"][name] == fixtures.workloads()[name], f"Imported workload differs: {name}"
        prefix = Path("fixtures") / name
        expected = {str(Path(relative).relative_to(prefix)): sha for relative, sha in manifest.items()
                    if Path(relative).is_relative_to(prefix)}
        source = source_root / prefix
        actual = {str(path.relative_to(source)) for path in source.rglob("*") if path.is_file()}
        assert expected and set(expected) == actual, name
        for relative, sha in expected.items():
            assert digest(source / relative) == sha, f"Historical fixture changed: {name}/{relative}"
        clone_dataset(source, ROOT / "fixtures" / name)
        registered = register_fixture(name, dict(kind="import", source_root=str(source_root),
            source_freeze_sha256=digest(source_root / "freeze.json"),
            source_manifest_sha256=digest(manifest_path), source_generator_sha256=digest(source_generator)))
        assert registered["files"] == expected, f"Imported file identity differs: {name}"


def proc_rss(pid):
    try:
        return {name.rstrip(":"): int(value) * 1024 for name, value, _ in (
            line.split() for line in Path(f"/proc/{pid}/status").read_text().splitlines()
            if line.startswith(("VmRSS:", "VmHWM:", "RssAnon:", "RssFile:", "RssShmem:")))}
    except (FileNotFoundError, ProcessLookupError):
        return {}


def proc_io():
    return {name: int(value) for name, value in
            (line.split(": ") for line in Path("/proc/self/io").read_text().splitlines())}


def controls(group):
    return {name: (group / name).read_text().strip() for name in (
        "memory.max", "memory.swap.max", "memory.current", "memory.peak", "memory.events",
        "memory.oom.group", "memory.stat", "cpu.max", "cpu.stat", "cgroup.events")}


def temporary_files(folder):
    files = []
    for path in sorted(folder.rglob("*")):
        try:
            if path.is_file():
                stat = path.stat()
                files.append(dict(path=str(path.relative_to(folder)), bytes=stat.st_size,
                                  allocated_bytes=stat.st_blocks * 512))
        except FileNotFoundError:
            pass
    return files


def isolated(operation, variant, directory, pool=GIB, limit=8 * GIB, timeout=1200):
    parent = Path(config()["cgroup_parent"])
    assert not (parent / "cgroup.procs").read_text().strip(), "Coordinator must stay outside the experiment parent"
    for child in parent.iterdir():
        if child.is_dir() and (child / "cgroup.events").exists():
            assert "populated 1" not in (child / "cgroup.events").read_text(), f"Active worker: {child}"
    group = parent / f"{directory.name}-{operation}"
    group.mkdir()
    for name in ("memory.max", "memory.swap.max", "memory.oom.group", "cpu.max", "cgroup.kill"):
        assert (group / name).exists(), f"Missing real cgroup control: {group / name}"
    (group / "memory.max").write_text(str(limit))
    (group / "memory.swap.max").write_text("0")
    (group / "memory.oom.group").write_text("1")
    before = controls(group)
    assert int(before["memory.max"]) == limit and before["memory.swap.max"] == "0"
    cmd, cwd = command(variant, "worker", operation, str(directory))
    temporary = directory / f"{operation}-tmp"
    temporary.mkdir(exist_ok=False)
    worker_environment = environment(variant, pool)
    worker_environment["TMPDIR"] = str(temporary)
    tmp_peak_bytes = tmp_peak_allocated_bytes = tmp_peak_count = 0

    def enter():
        os.setsid()
        (group / "cgroup.procs").write_text(str(os.getpid()))

    started, cancelled = time.monotonic(), False
    with (directory / f"{operation}.log").open("w") as log, \
            (directory / f"{operation}-memory.jsonl").open("w", buffering=1) as samples:
        process = subprocess.Popen(cmd, cwd=cwd, env=worker_environment, stdout=log,
                                   stderr=subprocess.STDOUT, preexec_fn=enter)
        while process.poll() is None:
            members = [int(pid) for pid in (group / "cgroup.procs").read_text().split()]
            observed = max((proc_rss(pid) for pid in members), key=lambda item: item.get("VmRSS", 0), default={})
            memory_stat = dict(line.split() for line in (group / "memory.stat").read_text().splitlines())
            temporary_state = temporary_files(temporary)
            tmp_bytes = sum(item["bytes"] for item in temporary_state)
            tmp_allocated = sum(item["allocated_bytes"] for item in temporary_state)
            tmp_peak_bytes = max(tmp_peak_bytes, tmp_bytes)
            tmp_peak_allocated_bytes = max(tmp_peak_allocated_bytes, tmp_allocated)
            tmp_peak_count = max(tmp_peak_count, len(temporary_state))
            samples.write(json.dumps(dict(t=time.monotonic(), pids=members, **observed,
                tmp_bytes=tmp_bytes, tmp_allocated_bytes=tmp_allocated, tmp_files=len(temporary_state),
                cgroup_anon=int(memory_stat["anon"]), cgroup_file=int(memory_stat["file"]),
                cgroup_shmem=int(memory_stat["shmem"]),
                cgroup_current=int((group / "memory.current").read_text()),
                cgroup_peak=int((group / "memory.peak").read_text()))) + "\n")
            if time.monotonic() - started > timeout and not cancelled:
                cancelled = True
                (group / "cgroup.kill").write_text("1")
            time.sleep(0.01)
    after = controls(group)
    events = lambda value: {key: int(count) for key, count in (line.split() for line in value.splitlines())}
    delta = {key: value - events(before["memory.events"])[key] for key, value in events(after["memory.events"]).items()}
    result = dict(operation=operation, variant=variant, command=cmd, cwd=str(cwd), cgroup=str(group),
        exit_code=process.returncode, timeout=cancelled, confirmed_oom=delta["oom_kill"] > 0,
        before=before, after=after, memory_event_delta=delta, configured_pool_bytes=pool,
        pool_policy=config()["variants"][variant]["pool_policy"], coordinator_seconds=time.monotonic() - started,
        temporary_directory=str(temporary), sampled_tmp_peak_bytes=tmp_peak_bytes,
        sampled_tmp_peak_allocated_bytes=tmp_peak_allocated_bytes, sampled_tmp_peak_file_count=tmp_peak_count,
        tmp_files_at_exit=temporary_files(temporary),
        tmp_interpretation="Sampled live file footprint, not cumulative writes; short-lived or already-unlinked files may be missed")
    deadline = time.monotonic() + 5
    while True:
        try:
            group.rmdir()
            break
        except OSError as error:
            if error.errno != errno.EBUSY or time.monotonic() >= deadline:
                result["cleanup_error"] = str(error)
                break
            time.sleep(0.05)
    save(directory / f"{operation}-resources.json", result)
    return result


def residency(path):
    size = path.stat().st_size
    if not size:
        return dict(bytes=0, pages=0, resident_pages=0)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.restype = ctypes.c_void_p
    libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_longlong]
    libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_ubyte)]
    libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    pages = (size + os.sysconf("SC_PAGE_SIZE") - 1) // os.sysconf("SC_PAGE_SIZE")
    with path.open("rb") as source:
        address = libc.mmap(None, size, 0, 1, source.fileno(), 0)
        if address == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_errno(), "mmap for mincore failed")
        try:
            vector = (ctypes.c_ubyte * pages)()
            if libc.mincore(address, size, vector):
                raise OSError(ctypes.get_errno(), "mincore failed")
            return dict(bytes=size, pages=pages, resident_pages=sum(value & 1 for value in vector))
        finally:
            libc.munmap(address, size)


def cache_state(directory, manifest, mode=None):
    records = []
    for relative in manifest["files"]:
        if Path(relative).suffix != ".lance":
            continue
        path = directory / "dataset" / relative
        item = dict(file=relative)
        try:
            item["before"] = residency(path)
        except OSError as error:
            item["before_error"] = str(error)
        if mode == "hot":
            with path.open("rb") as source:
                while source.read(8 << 20):
                    pass
        elif mode == "evict_attempt":
            try:
                with path.open("rb") as source:
                    os.fsync(source.fileno())
                    os.posix_fadvise(source.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                item["fadvise_returned"] = True
            except OSError as error:
                item["fadvise_error"] = str(error)
        try:
            item["after"] = residency(path)
        except OSError as error:
            item["after_error"] = str(error)
        records.append(item)
    return dict(mode=mode or "observation_only", files=records,
                interpretation="fadvise is advisory; mincore residency and actual execute read_bytes are separate evidence")


def execute(directory, analyze=False):
    import lance
    import pyarrow as pa

    spec, cell = read(directory / "spec.json"), read(directory / "cell.json")
    uri = directory / "dataset"
    ds = lance.dataset(str(uri))
    metrics = dict(status="started", operation="analyze" if analyze else "execute", snapshot=ds.version, identity=identity(), schema=str(ds.schema),
                   configured_pool_bytes=cell["pool_bytes"], pool_policy=config()["variants"][cell["variant"]]["pool_policy"],
                   baseline_rss=proc_rss(os.getpid()), input_materialization_seconds=0)
    save(directory / "metrics.json", metrics)
    source = pa.RecordBatchReader.from_batches(fixtures.schema(spec, source=True), fixtures.source_batches(spec, directory))
    if cell["input_form"] == "materialized":
        started = time.perf_counter()
        source = source.read_all()
        metrics["input_materialization_seconds"] = time.perf_counter() - started
    builder = (ds.merge_insert("id").when_matched_update_all(spec.get("condition"))
               .use_index(False).write_mode(cell["write_mode"]).conflict_retries(0))
    if spec["full"]:
        builder = builder.when_not_matched_insert_all()
    initial_files = {str(path) for path in uri.rglob("*.lance")}
    metrics["execute_rss_before"] = proc_rss(os.getpid())
    metrics["ru_maxrss_before_execute_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    save(directory / "metrics.json", metrics)
    cpu_start, io_start, started = resource.getrusage(resource.RUSAGE_SELF), proc_io(), time.perf_counter()
    try:
        if analyze:
            plan = builder.analyze_plan(source)
            (directory / "analyzed-plan.txt").write_text(plan)
            metrics["analyzed_plan_sha256"] = digest(directory / "analyzed-plan.txt")
            metrics["status"] = "analyze_returned"
        else:
            metrics["merge_stats"] = builder.execute(source)
            metrics["status"] = "execute_returned"
    except Exception as error:
        message = str(error)
        exhausted = any(term in message.lower() for term in ("resources exhausted", "resource exhausted", "failed to allocate"))
        metrics.update(status="resource_exhausted" if exhausted else "execution_error", error=message,
                       error_type=type(error).__name__, traceback=traceback.format_exc())
    elapsed = time.perf_counter() - started
    metrics["analyze_seconds" if analyze else "merge_seconds"] = elapsed
    cpu_end, io_end = resource.getrusage(resource.RUSAGE_SELF), proc_io()
    metrics["cpu_seconds"] = cpu_end.ru_utime + cpu_end.ru_stime - cpu_start.ru_utime - cpu_start.ru_stime
    metrics["process_io_delta"] = {key: value - io_start[key] for key, value in io_end.items()}
    metrics["ru_maxrss_bytes"] = cpu_end.ru_maxrss * 1024
    metrics["ru_maxrss_after_execute_bytes"] = cpu_end.ru_maxrss * 1024
    metrics["execute_rss_after"] = proc_rss(os.getpid())
    added = [path for path in uri.rglob("*.lance") if str(path) not in initial_files]
    metrics["new_data_file_bytes"], metrics["new_data_file_count"] = sum(path.stat().st_size for path in added), len(added)
    metrics["input_and_api_seconds"] = metrics["input_materialization_seconds"] + elapsed
    save(directory / "metrics.json", metrics)


def all_results():
    return [read(path) for path in sorted((ROOT / "runs").glob("*/result.json"))]


def producer_statistics(directory):
    path = directory / "producer.jsonl"
    records, truncated = [], False
    if path.exists():
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                assert index == len(lines) - 1, "Malformed producer record before the final line"
                truncated = True
    return dict(yielded_batches=len(records), yielded_rows=sum(item["rows"] for item in records),
                yielded_arrow_bytes=sum(item["bytes"] for item in records),
                truncated_final_record=truncated,
                interpretation="Generator yields observed; EOF polls and downstream retention are not measured")


def cell_contract(cell, frozen, manifest):
    return dict(cell={key: value for key, value in cell.items() if key not in ("block", "run_id")},
                identity=content_identity(frozen["identities"][cell["variant"]]),
                fixture_files=manifest["files"], spec=manifest["metadata"]["spec"],
                variant_environment=frozen["config"]["variants"][cell["variant"]].get("environment", {}))


def run_cell(plan, cell, frozen):
    no_builds()
    manifest = plan["fixtures"][cell["workload"]]
    contract = cell_contract(cell, frozen, manifest)
    diagnostic = plan["kind"] == "diagnose"
    previous = [row for row in all_results() if row.get("contract") == contract and
                row["status"] in ("confirmed_oom", "resource_exhausted") and row.get("atomicity_validated")]
    if previous and not diagnostic:
        result = dict(run_id=cell["run_id"], plan=plan["name"], cell=cell, executed=False,
                      status="not_repeated_after_resource_failure", prior=previous[0], contract=contract,
                      atomicity_validated=previous[0].get("atomicity_validated", False))
        reference = ROOT / "references" / f'{cell["run_id"]}.json'
        if reference.exists():
            raise FileExistsError(reference)
        save(reference, result)
        return result
    directory = ROOT / ("diagnostics" if diagnostic else "runs") / cell["run_id"]
    directory.mkdir(parents=True, exist_ok=False)
    spec = fixtures.workloads()[cell["workload"]] | dict(write_mode=cell["write_mode"])
    save(directory / "spec.json", spec)
    save(directory / "cell.json", cell)
    save(directory / "initial-snapshot.json", manifest["metadata"])
    clone_dataset(ROOT / "fixtures" / cell["workload"], directory / "dataset")
    save(directory / "cache-before.json", cache_state(directory, manifest, cell["cache"]))
    append(ROOT / "events.jsonl", dict(run_id=cell["run_id"], status="started", cell=cell))
    api_operation = "analyze" if diagnostic else "execute"
    execution = isolated(api_operation, cell["variant"], directory, cell["pool_bytes"], cell["cgroup_bytes"], cell["timeout_seconds"])
    save(directory / "cache-after-execute.json", cache_state(directory, manifest))
    metrics = read(directory / "metrics.json") if (directory / "metrics.json").exists() else {}
    status = "confirmed_oom" if execution["confirmed_oom"] else "timeout" if execution["timeout"] else metrics.get("status", "infrastructure_error")
    if execution["exit_code"] != 0 and status not in ("confirmed_oom", "timeout"):
        status = "infrastructure_error"
    if metrics.get("identity") != frozen["identities"][cell["variant"]]["imported"]:
        status = "infrastructure_error"
    producer = producer_statistics(directory)
    if status in ("execute_returned", "analyze_returned") and (
            producer["yielded_rows"] != spec["source_rows"] or producer["truncated_final_record"]):
        status = "source_consumption_error"
    validator = config()["validator"]
    status_before_validation = status
    operation = "validate" if status == "execute_returned" else "validate_unchanged"
    checked = isolated(operation, validator, directory, GIB, cell["cgroup_bytes"], max(cell["timeout_seconds"], 3600))
    oracle = read(directory / f"{operation}.json") if (directory / f"{operation}.json").exists() else {}
    valid = (checked["exit_code"] == 0 and oracle.get("validated") is True and
             oracle.get("validator_identity") == frozen["identities"][validator]["imported"])
    if status == "execute_returned":
        status = "validated_success" if valid else "validation_error"
    elif status == "analyze_returned":
        status = "validated_diagnostic" if valid else "failed_atomicity_check"
    elif not valid:
        status = "failed_atomicity_check"
    if "cleanup_error" in execution or "cleanup_error" in checked:
        status = "infrastructure_error"
    samples = [json.loads(line) for line in (directory / f"{api_operation}-memory.jsonl").read_text().splitlines()]
    result = metrics | dict(run_id=cell["run_id"], plan=plan["name"], kind=plan["kind"], cell=cell,
        contract=contract, status=status, status_before_validation=status_before_validation,
        executed=True, execution=execution, validation=checked, producer=producer,
        atomicity_validated=operation == "validate_unchanged" and valid,
        sampled_peak_rss_bytes=max((sample.get("VmRSS", 0) for sample in samples), default=0),
        cgroup_peak_bytes=int(execution["after"]["memory.peak"]))
    save(directory / "result.json", result)
    append(ROOT / "events.jsonl", dict(run_id=cell["run_id"], status=status))
    return result


def summarize():
    results = all_results()
    references = [read(path) for path in sorted((ROOT / "references").glob("*.json"))]
    comparisons = []
    for path in sorted((ROOT / "plans").glob("*.json")):
        plan = read(path)
        if plan["kind"] != "pairs":
            continue
        for workload in plan["workloads"]:
            for top, bottom in plan["comparisons"]:
                ratios = []
                for block in (1, 2, 3):
                    group = {f'{row["cell"]["variant"]}/{row["cell"]["write_mode"]}': row for row in results
                             if row["plan"] == plan["name"] and row["cell"]["workload"] == workload
                             and row["cell"]["block"] == block and row["status"] == "validated_success"}
                    if top in group and bottom in group:
                        ratios.append(dict(block=block, ratio=group[top]["merge_seconds"] / group[bottom]["merge_seconds"]))
                comparisons.append(dict(plan=plan["name"], workload=workload, numerator=top, denominator=bottom,
                    planned_pairs=3, valid_pairs=len(ratios), ratios=ratios,
                    median_ratio=statistics.median(item["ratio"] for item in ratios) if ratios else None))
    save(ROOT / "summary.json", dict(
        actual_executions=len(results), statuses={status: sum(row["status"] == status for row in results)
            for status in sorted({row["status"] for row in results})},
        results=[{key: row.get(key) for key in ("run_id", "plan", "kind", "cell", "status", "merge_seconds",
            "cpu_seconds", "new_data_file_bytes", "new_data_file_count", "sampled_peak_rss_bytes",
            "cgroup_peak_bytes", "process_io_delta", "atomicity_validated", "producer")} for row in results],
        diagnostics=[read(path) for path in sorted((ROOT / "diagnostics").glob("*/result.json"))],
        references=references, paired_comparisons=comparisons))


def main():
    global ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--config", required=True, type=Path)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--name", required=True)
    freeze.add_argument("--variants", required=True)
    imported = sub.add_parser("import-fixtures")
    imported.add_argument("--source-root", required=True, type=Path)
    imported.add_argument("--workloads", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--freeze", required=True)
    generate.add_argument("--workloads", required=True)
    plan = sub.add_parser("make-plan")
    plan.add_argument("--name", required=True)
    plan.add_argument("--freeze", required=True)
    plan.add_argument("--kind", required=True, choices=("correctness", "survival", "pairs", "cold", "diagnose"))
    plan.add_argument("--variants", required=True)
    plan.add_argument("--workloads", default="")
    plan.add_argument("--modes", default="rewrite_rows")
    plan.add_argument("--pool-mib", type=int, default=1024)
    plan.add_argument("--cgroup-mib", type=int, default=8192)
    plan.add_argument("--input-form", choices=("reader", "materialized"), default="reader")
    plan.add_argument("--cache", choices=("hot", "evict_attempt"), default="hot")
    plan.add_argument("--comparisons", default="")
    plan.add_argument("--timeout", type=int, default=1200)
    run = sub.add_parser("run")
    run.add_argument("plan")
    sub.add_parser("summarize")
    sub.add_parser("identity")
    worker = sub.add_parser("worker")
    worker.add_argument("operation", choices=("execute", "analyze", "validate", "validate_unchanged", "generate"))
    worker.add_argument("directory", type=Path)
    args = parser.parse_args()
    ROOT = args.root.resolve()
    if args.action == "identity":
        sys.stdout.write(json.dumps(identity()) + "\n")
        return
    if args.action == "worker":
        spec = read(args.directory / "spec.json")
        if args.operation in ("execute", "analyze"):
            execute(args.directory, analyze=args.operation == "analyze")
        elif args.operation == "generate":
            fixtures.generate(spec, ROOT / "fixtures" / spec["name"])
            save(args.directory / "generate.json", dict(identity=identity(), generated=True))
        else:
            result = fixtures.validate(spec, args.directory, unchanged=args.operation == "validate_unchanged")
            save(args.directory / f"{args.operation}.json", result | dict(validator_identity=identity()))
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / ".coordinator.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "init":
            if (ROOT / "config.json").exists():
                raise FileExistsError(ROOT / "config.json")
            cfg = read(args.config)
            assert cfg["validator"] in cfg["variants"]
            cfg.setdefault("uv", shutil.which("uv"))
            assert cfg["uv"]
            for variant in cfg["variants"].values():
                assert "LANCE_MEM_POOL_SIZE" not in variant.get("environment", {})
                assert Path(variant["checkout"]).is_absolute() and Path(variant["build_log"]).is_absolute()
            save(ROOT / "config.json", cfg)
        elif args.action == "freeze":
            destination = ROOT / "freezes" / f"{args.name}.json"
            if destination.exists():
                raise FileExistsError(destination)
            labels = args.variants.split(",")
            if config()["validator"] not in labels:
                labels.append(config()["validator"])
            save(destination, current_freeze(labels))
        elif args.action == "import-fixtures":
            import_fixtures(args.source_root, args.workloads.split(","))
        elif args.action == "generate":
            frozen = verify_freeze(args.freeze)
            validator = config()["validator"]
            (ROOT / "fixtures").mkdir(exist_ok=True)
            for name in args.workloads.split(","):
                directory = ROOT / "setup" / name
                directory.mkdir(parents=True, exist_ok=False)
                save(directory / "spec.json", fixtures.workloads()[name])
                save(directory / "environment.json", dict(active_builds=builds(), freeze=args.freeze,
                                                          note="Fixture generation is outside performance measurements"))
                result = isolated("generate", validator, directory, timeout=7200)
                assert result["exit_code"] == 0 and not result["confirmed_oom"] and not result["timeout"], result
                assert read(directory / "generate.json")["identity"] == frozen["identities"][validator]["imported"]
                register_fixture(name, dict(kind="generated", freeze=args.freeze,
                    freeze_sha256=digest(ROOT / "freezes" / f"{args.freeze}.json"),
                    generator_identity=frozen["identities"][validator]["imported"]))
            verify_freeze(args.freeze)
        elif args.action == "make-plan":
            frozen = verify_freeze(args.freeze)
            labels, modes = args.variants.split(","), args.modes.split(",")
            assert all(label in frozen["labels"] for label in labels)
            assert all(mode in ("rewrite_rows", "rewrite_columns") for mode in modes)
            names = args.workloads.split(",") if args.workloads else ["tiny", "string_null", "condition_overlap", "condition_reject"]
            assert args.workloads or args.kind == "correctness"
            assert args.pool_mib > 0 and args.cgroup_mib > 0 and args.timeout > 0
            assert args.kind != "cold" or (len(names) == 1 and args.cache == "evict_attempt")
            captured = {name: verify_fixture(name) for name in names}
            cells, rng = [], random.Random(950519)
            for block in range(1, 4) if args.kind == "pairs" else (0,):
                for name in names:
                    order = [(label, mode) for label in labels for mode in modes]
                    if args.kind == "pairs":
                        rng.shuffle(order)
                    for label, mode in order:
                        cells.append(dict(run_id=f"{args.name}-{name}-{label}-{mode}-b{block}", workload=name,
                            variant=label, write_mode=mode, block=block, pool_bytes=args.pool_mib << 20,
                            cgroup_bytes=args.cgroup_mib << 20, cache=args.cache, input_form=args.input_form,
                            timeout_seconds=args.timeout))
            comparisons = [pair.split(":") for pair in args.comparisons.split(",") if pair]
            choices = [f"{label}/{mode}" for label in labels for mode in modes]
            assert all(len(pair) == 2 and all(item in choices for item in pair) for pair in comparisons)
            if args.kind == "pairs":
                assert comparisons, "Register the intended paired comparisons explicitly"
            if args.kind in ("pairs", "diagnose"):
                previous = all_results()
                for cell in cells:
                    contract = cell_contract(cell, frozen, captured[cell["workload"]])
                    assert any(row.get("contract") == contract and row["status"] == "validated_success"
                               and row["kind"] in ("survival", "cold") for row in previous), \
                        f'No successful survival run for {cell["variant"]}/{cell["workload"]}/{cell["write_mode"]}'
            destination = ROOT / "plans" / f"{args.name}.json"
            if destination.exists():
                raise FileExistsError(destination)
            save(destination, dict(name=args.name, freeze=args.freeze,
                freeze_sha256=digest(ROOT / "freezes" / f"{args.freeze}.json"), kind=args.kind,
                workloads=names, cells=cells, fixtures=captured, comparisons=comparisons))
        elif args.action == "run":
            no_builds()
            plan = read(ROOT / "plans" / f"{args.plan}.json")
            assert digest(ROOT / "freezes" / f'{plan["freeze"]}.json') == plan["freeze_sha256"]
            frozen = verify_freeze(plan["freeze"])
            for name, manifest in plan["fixtures"].items():
                verify_fixture(name, manifest)
            if plan["kind"] != "correctness":
                previous = all_results()
                for label in {cell["variant"] for cell in plan["cells"]}:
                    for name in ("tiny", "string_null", "condition_overlap", "condition_reject"):
                        assert any(row["kind"] == "correctness" and row["status"] == "validated_success"
                            and row["cell"]["variant"] == label and row["cell"]["workload"] == name
                            and row["contract"]["identity"] == content_identity(frozen["identities"][label])
                            for row in previous), f"Missing correctness gate: {label}/{name}"
            completed = []
            for cell in plan["cells"]:
                result = run_cell(plan, cell, frozen)
                completed.append(result)
                accepted = result["status"] in ("validated_success", "validated_diagnostic") or (plan["kind"] == "survival"
                    and result.get("atomicity_validated") and result["status"] in (
                        "confirmed_oom", "resource_exhausted", "not_repeated_after_resource_failure"))
                save(ROOT / "gates" / f'{plan["name"]}.json', dict(
                    plan=plan["name"], planned=len(plan["cells"]), completed=len(completed),
                    complete=len(completed) == len(plan["cells"]),
                    candidate_passed=all(row["status"] in ("validated_success", "validated_diagnostic") for row in completed
                        if config()["variants"][row["cell"]["variant"]].get("role") != "baseline"),
                    statuses=[dict(run_id=row["run_id"], status=row["status"], executed=row["executed"])
                              for row in completed]))
                summarize()
                if not accepted:
                    raise RuntimeError(f'{cell["run_id"]}: {result["status"]}; inspect before scheduling another plan')
            verify_freeze(plan["freeze"])
        else:
            summarize()


if __name__ == "__main__":
    main()
