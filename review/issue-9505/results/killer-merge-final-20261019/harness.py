"""Isolated current-main/K merge execution, validation and evidence collection."""

import argparse
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

ROOT = Path(__file__).resolve().parent
GIB = 1 << 30
POOL = GIB
LIMIT = 8 * GIB
PRIOR_RUN = "smoke-F16-U_main-rewrite_rows-b0"


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def append(path, value):
    with path.open("a", buffering=1) as output:
        output.write(json.dumps(dict(wall_ns=time.time_ns()) | value) + "\n")


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def config():
    return json.loads((ROOT / "config.json").read_text())


def clean_environment():
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith("LANCE_MERGE_") or name in (
                "LANCE_BYPASS_SPILLING", "PYTHONPATH", "PYTHONHOME"):
            environment.pop(name)
    environment["LANCE_MEM_POOL_SIZE"] = str(POOL)
    return environment


def command(variant, *arguments):
    cfg = config()
    return ([cfg["uv"], "run", "--no-sync", "python", str(ROOT / "harness.py"),
             *arguments], Path(cfg["checkouts"][variant]) / "python")


def no_builds():
    names = subprocess.check_output(["ps", "-eo", "comm="], text=True).splitlines()
    active = [name for name in names if Path(name.strip()).name in ("cargo", "rustc", "maturin")]
    if active:
        raise RuntimeError(f"Compilation is active: {active}")


def identity():
    import lance
    import pyarrow

    extension = Path(importlib.util.find_spec("lance.lance").origin).resolve()
    return dict(module=str(Path(lance.__file__).resolve()), extension=str(extension),
                extension_sha256=digest(extension), version=lance.__version__,
                python=sys.version, pyarrow=pyarrow.__version__)


def tree_identity(checkout):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(checkout), *args])

    names = set(git("ls-files", "-z").decode().split("\0"))
    names |= set(git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0"))
    names = sorted(name for name in names if name and (
        name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml") or
        (name.startswith(("rust/", "python/", ".cargo/")) and
         Path(name).suffix in (".rs", ".py", ".toml", ".lock", ".mk")) or
        name == "python/Makefile"))
    hashes = {name: digest(checkout / name) for name in names if (checkout / name).is_file()}
    return dict(head=git("rev-parse", "HEAD").decode().strip(),
                tracked_status=git("status", "--porcelain", "--untracked-files=no").decode(),
                diff_sha256=hashlib.sha256(git("diff", "HEAD", "--binary")).hexdigest(),
                source_hashes=hashes)


def prior_failure_evidence(cfg, baseline):
    source_root = Path(cfg["prior_failure_root"])
    assert source_root != ROOT, "The prior evidence must use a different result root"
    paths = {
        "freeze": source_root / "freeze.json",
        "fixture_hashes": source_root / "fixture-hashes.json",
        **{name: source_root / "runs" / PRIOR_RUN / f"{name}.json" for name in (
            "result", "spec", "metrics", "execute-resources", "validate_unchanged",
            "validate_unchanged-resources")},
    }
    evidence = {name: json.loads(path.read_text()) for name, path in paths.items()}
    prior = evidence["freeze"]
    assert prior["config"]["base_commit"] == cfg["base_commit"]
    assert prior["workloads"] == fixtures.workloads(), "Prior workload definitions differ"
    assert prior["identities"]["U_main"] == baseline, "Prior baseline source or binary differs"
    assert prior["build_logs"]["U_main"]["sha256"] == digest(cfg["build_logs"]["U_main"])
    for name, expected in prior["harness"].items():
        assert digest(source_root / name) == expected, f"Prior harness changed: {name}"
    assert prior["harness"]["fixtures.py"] == digest(ROOT / "fixtures.py"), \
        "Fixture generation and full-field oracle must remain identical"
    for name, expected in prior["build_environment"].items():
        assert os.environ.get(name) == expected, f"Prior build/runtime setting differs: {name}"

    spec = fixtures.workloads()["F16"] | dict(write_mode="rewrite_rows")
    assert evidence["spec"] == spec, "Prior F16 execution specification differs"
    result = evidence["result"]
    metrics = evidence["metrics"]
    assert all(result[key] == value for key, value in dict(
        run_id=PRIOR_RUN, stage="smoke", block=0, workload="F16", variant="U_main",
        write_mode="rewrite_rows", status="confirmed_oom", configured_pool_bytes=POOL).items())
    assert result["identity"] == metrics["identity"] == baseline["imported"]
    assert result["snapshot"] == metrics["snapshot"] == 1
    assert result["schema"] == metrics["schema"]
    assert metrics["configured_pool_bytes"] == POOL
    assert result["execution"] == evidence["execute-resources"]
    execution = evidence["execute-resources"]
    validation = evidence["validate_unchanged-resources"]
    for operation, resources in (("execute", execution), ("validate_unchanged", validation)):
        assert resources["operation"] == operation and resources["variant"] == "U_main"
        assert resources["configured_pool_bytes"] == POOL and not resources["timeout"]
        assert "cleanup_error" not in resources, resources
        before_state = dict(line.split() for line in resources["before"]["cgroup.events"].splitlines())
        assert before_state["populated"] == "0", resources
        assert resources["command"] == [
            prior["config"]["uv"], "run", "--no-sync", "python",
            str(source_root / "harness.py"), "worker", operation,
            str(source_root / "runs" / PRIOR_RUN)], resources["command"]
        for moment in ("before", "after"):
            assert int(resources[moment]["memory.max"]) == LIMIT
            assert int(resources[moment]["memory.swap.max"]) == 0
    before_events = dict(line.split() for line in execution["before"]["memory.events"].splitlines())
    after_events = dict(line.split() for line in execution["after"]["memory.events"].splitlines())
    assert execution["confirmed_oom"] and execution["exit_code"] == -9
    assert int(after_events["oom_kill"]) > int(before_events["oom_kill"])
    assert validation["exit_code"] == 0 and not validation["confirmed_oom"]
    oracle = evidence["validate_unchanged"]
    assert oracle["validated"] and oracle["unchanged"]
    assert oracle["version"] == result["snapshot"] and oracle["rows"] == spec["rows"]
    assert oracle["expected_counts"] == dict(
        num_updated_rows=0, num_inserted_rows=0, num_deleted_rows=0)
    assert oracle["oracle"] == "splitmix64-v1-all-fields"
    assert set(oracle["hashes"]) == {"id", *(f"c{i}" for i in range(spec["columns"] - 1))}
    hashes = evidence["fixture_hashes"]
    assert {Path(name).parts[1] for name in hashes} == set(fixtures.workloads())
    assert all(not Path(name).is_absolute() and ".." not in Path(name).parts
               and Path(name).parts[0] == "fixtures" for name in hashes)
    return dict(
        run_id=PRIOR_RUN, source_root=str(source_root),
        artifacts={name: dict(path=str(path), sha256=digest(path)) for name, path in paths.items()},
        baseline_extension_sha256=baseline["imported"]["extension_sha256"],
        prior_cgroup_parent=prior["config"]["cgroup"],
        configured_pool_bytes=POOL, cgroup_limit_bytes=LIMIT, swap_limit_bytes=0,
        snapshot=result["snapshot"], status="confirmed_oom", unchanged_validated=True,
        fixture_hashes=hashes,
    )


def current_freeze():
    cfg = config()
    no_builds()
    identities = {}
    for variant, path in cfg["checkouts"].items():
        cmd, cwd = command(variant, "identity")
        observed = json.loads(subprocess.check_output(cmd, cwd=cwd, env=clean_environment(), text=True))
        assert Path(observed["module"]).is_relative_to(Path(path).resolve()), observed
        assert Path(observed["extension"]).is_relative_to(Path(path).resolve()), observed
        identities[variant] = dict(tree=tree_identity(Path(path)), imported=observed)
    return dict(identities=identities, config=cfg, workloads=fixtures.workloads(),
                prior_failure=prior_failure_evidence(cfg, identities["U_main"]),
                harness={name: digest(ROOT / name)
                         for name in ("harness.py", "fixtures.py", "README.md")},
                build_logs={variant: dict(path=path, sha256=digest(path))
                            for variant, path in cfg["build_logs"].items()},
                build_environment={name: os.environ.get(name) for name in (
                    "RUSTFLAGS", "CARGO_BUILD_TARGET", "LANCE_CPU_THREADS",
                    "LANCE_IO_THREADS", "LANCE_DEFAULT_IO_BUFFER_SIZE")},
                host=dict(platform=platform.platform(), machine=platform.machine(),
                          cpu_count=os.cpu_count()))


def verify_freeze():
    expected = json.loads((ROOT / "freeze.json").read_text())
    current = current_freeze()
    assert current == expected, "Source, binary, configuration or harness changed after freeze"
    return current


def proc_rss(pid):
    try:
        values = {}
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "RssAnon:", "RssFile:")):
                name, value, _ = line.split()
                values[name.rstrip(":")] = int(value) * 1024
        return values
    except FileNotFoundError:
        return {}


def proc_io():
    return {name: int(value) for name, value in
            (line.split(": ") for line in Path("/proc/self/io").read_text().splitlines())}


def controls(group):
    return {name: (group / name).read_text().strip() for name in (
        "memory.max", "memory.swap.max", "memory.current", "memory.peak",
        "memory.events", "cpu.max", "cpu.stat", "cgroup.events")}


def isolated(operation, variant, directory, timeout=600):
    root = Path(config()["cgroup"])
    for old in root.iterdir():
        if old.is_dir() and (old / "cgroup.events").exists():
            state = dict(line.split() for line in (old / "cgroup.events").read_text().splitlines())
            if state.get("populated") != "0":
                raise RuntimeError(f"Existing worker is still active: {old}")
    group = root / f"{directory.name}-{operation}"
    group.mkdir()
    (group / "memory.max").write_text(str(LIMIT))
    (group / "memory.swap.max").write_text("0")
    (group / "memory.oom.group").write_text("1")
    before = controls(group)
    cmd, cwd = command(variant, "worker", operation, str(directory))

    def enter():
        os.setsid()
        (group / "cgroup.procs").write_text(str(os.getpid()))

    started = time.monotonic()
    cancelled = False
    with (directory / f"{operation}.log").open("w") as log, \
            (directory / f"{operation}-memory.jsonl").open("w", buffering=1) as samples:
        process = subprocess.Popen(cmd, cwd=cwd, env=clean_environment(), stdout=log,
                                   stderr=subprocess.STDOUT, preexec_fn=enter)
        while process.poll() is None:
            members = [int(pid) for pid in (group / "cgroup.procs").read_text().split()]
            observed = max((proc_rss(pid) for pid in members),
                           key=lambda item: item.get("VmRSS", 0), default={})
            samples.write(json.dumps(dict(t=time.monotonic(), **observed,
                cgroup_current=int((group / "memory.current").read_text()),
                cgroup_peak=int((group / "memory.peak").read_text()))) + "\n")
            if time.monotonic() - started > timeout and not cancelled:
                cancelled = True
                (group / "cgroup.kill").write_text("1")
            time.sleep(0.01)
    after = controls(group)
    events = dict(line.split() for line in after["memory.events"].splitlines())
    result = dict(operation=operation, variant=variant, command=cmd,
                  exit_code=process.returncode, timeout=cancelled,
                  confirmed_oom=int(events["oom_kill"]) > 0, before=before, after=after,
                  configured_pool_bytes=POOL,
                  pool_enforcement="Not inferred from the environment setting")
    save(directory / f"{operation}-resources.json", result)
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


def execute(spec, directory):
    import lance
    import pyarrow as pa

    uri = directory / "dataset"
    ds = lance.dataset(str(uri))
    metrics = dict(status="started", snapshot=ds.version, identity=identity(),
                   configured_pool_bytes=POOL, schema=str(ds.schema))
    save(directory / "metrics.json", metrics)
    source = pa.RecordBatchReader.from_batches(fixtures.schema(spec, source=True),
                                              fixtures.source_batches(spec, directory))
    builder = (ds.merge_insert("id").when_matched_update_all(spec.get("condition"))
               .use_index(False).write_mode(spec["write_mode"]).conflict_retries(0))
    if spec["full"]:
        builder = builder.when_not_matched_insert_all()
    initial_files = {str(path) for path in uri.rglob("*.lance")}
    cpu_start = resource.getrusage(resource.RUSAGE_SELF)
    io_start = proc_io()
    started = time.perf_counter()
    try:
        metrics["merge_stats"] = builder.execute(source)
        metrics["status"] = "execute_returned"
    except Exception as error:
        message = str(error)
        exhausted = any(term in message.lower() for term in (
            "resources exhausted", "resource exhausted", "failed to allocate"))
        metrics.update(status="resource_exhausted" if exhausted else "execution_error",
                       error=message, traceback=traceback.format_exc())
    metrics["merge_seconds"] = time.perf_counter() - started
    io_end = proc_io()
    cpu_end = resource.getrusage(resource.RUSAGE_SELF)
    metrics["cpu_seconds"] = (cpu_end.ru_utime + cpu_end.ru_stime
                              - cpu_start.ru_utime - cpu_start.ru_stime)
    metrics["process_io_delta"] = {key: value - io_start[key] for key, value in io_end.items()}
    metrics["ru_maxrss_bytes"] = cpu_end.ru_maxrss * 1024
    added = [path for path in uri.rglob("*.lance") if str(path) not in initial_files]
    metrics["new_data_file_bytes"] = sum(path.stat().st_size for path in added)
    metrics["new_data_file_count"] = len(added)
    save(directory / "metrics.json", metrics)


def clone_dataset(source, destination):
    def copy(src, dst):
        if Path(src).suffix == ".lance":
            os.link(src, dst)
            return dst
        return shutil.copy2(src, dst)

    shutil.copytree(source, destination, copy_function=copy)


def verify_fixture_files(root, expected):
    actual = {str(path.relative_to(root)) for path in (root / "fixtures").rglob("*")
              if path.is_file()}
    assert actual == set(expected), "Fixture file set differs from the frozen prior manifest"
    for name, value in expected.items():
        assert digest(root / name) == value, f"Fixture hash differs: {name}"
    for name, spec in fixtures.workloads().items():
        metadata = json.loads((root / "fixtures" / name / "fixture.json").read_text())
        assert metadata["spec"] == spec, f"Fixture specification differs: {name}"
        assert metadata["rows"] == spec["rows"], metadata
        fragments = (spec["rows"] + spec["fragment_rows"] - 1) // spec["fragment_rows"]
        assert metadata["fragments"] == fragments, metadata
        assert metadata["version"] == 1, metadata


def import_fixtures(frozen):
    evidence = frozen["prior_failure"]
    source_root = Path(evidence["source_root"])
    expected = evidence["fixture_hashes"]
    verify_fixture_files(source_root, expected)
    destination = ROOT / "fixtures"
    destination.mkdir(exist_ok=False)
    for name in fixtures.workloads():
        clone_dataset(source_root / "fixtures" / name, destination / name)
    verify_fixture_files(ROOT, expected)
    save(ROOT / "fixture-hashes.json", expected)
    save(ROOT / "fixture-import.json", dict(
        source_root=str(source_root), source_manifest=evidence["artifacts"]["fixture_hashes"],
        workloads=list(fixtures.workloads()), files=len(expected),
        method="Hard links for immutable .lance files; metadata copied",
    ))


def records():
    return [json.loads(path.read_text()) for path in sorted((ROOT / "runs").glob("*/result.json"))]


def run_cell(stage, workload, variant, mode, block=0):
    no_builds()
    name = f"{stage}-{workload}-{variant}-{mode}-b{block}"
    directory = ROOT / "runs" / name
    spec = fixtures.workloads()[workload] | dict(write_mode=mode)
    if (workload, variant, mode) == ("F16", "U_main", "rewrite_rows"):
        assert stage in ("smoke", "pairs"), stage
        prior = json.loads((ROOT / "freeze.json").read_text())["prior_failure"]
        reference = ROOT / "references" / f"{name}.json"
        if reference.exists() or directory.exists():
            raise FileExistsError(reference)
        result = dict(run_id=name, stage=stage, block=block, workload=workload,
                      variant=variant, write_mode=mode, executed=False,
                      status="not_repeated_after_resource_failure", prior_run_id=prior["run_id"],
                      prior_artifacts=prior["artifacts"],
                      prior_extension_sha256=prior["baseline_extension_sha256"],
                      configured_pool_bytes=POOL, cgroup_limit_bytes=LIMIT)
        save(reference, result)
        append(ROOT / "runs.jsonl", result)
        return result
    previous = [row for row in records() if row["workload"] == workload
                and row["variant"] == variant and row["write_mode"] == mode
                and row["status"] in ("confirmed_oom", "resource_exhausted")]
    if previous:
        return dict(run_id=name, workload=workload, variant=variant, write_mode=mode,
                    status="not_repeated_after_resource_failure", executed=False,
                    prior=previous[0]["run_id"])
    directory.mkdir(parents=True, exist_ok=False)
    save(directory / "spec.json", spec)
    clone_dataset(ROOT / "fixtures" / workload, directory / "dataset")
    for path in (directory / "dataset").rglob("*.lance"):
        with path.open("rb") as source:
            while source.read(8 << 20):
                pass
    append(ROOT / "runs.jsonl", dict(run_id=name, status="started", spec=spec,
                                    variant=variant, stage=stage, block=block))
    execution = isolated("execute", variant, directory)
    metric_path = directory / "metrics.json"
    metrics = json.loads(metric_path.read_text()) if metric_path.exists() else {}
    status = ("confirmed_oom" if execution["confirmed_oom"] else "timeout"
              if execution["timeout"] else metrics.get("status", "infrastructure_error"))
    if execution["exit_code"] != 0 and status not in ("confirmed_oom", "timeout"):
        status = "infrastructure_error"
    if status == "execute_returned":
        check = isolated("validate", "U_main", directory)
        status = "validated_success" if check["exit_code"] == 0 else "validation_error"
    elif status in ("confirmed_oom", "resource_exhausted"):
        if "snapshot" not in metrics:
            metrics["unverified_resource_status"] = status
            metrics["error"] = "Worker failed before recording the dataset snapshot"
            status = "infrastructure_error"
        else:
            check = isolated("validate_unchanged", "U_main", directory)
            if check["exit_code"] != 0:
                status = "failed_atomicity_check"
    samples = [json.loads(line) for line in
               (directory / "execute-memory.jsonl").read_text().splitlines()]
    result = metrics | dict(run_id=name, stage=stage, block=block, workload=workload,
        variant=variant, write_mode=mode, status=status, execution=execution,
        sampled_peak_rss_bytes=max((row.get("VmRSS", 0) for row in samples), default=0),
        cgroup_peak_bytes=int(execution["after"]["memory.peak"]))
    save(directory / "result.json", result)
    append(ROOT / "runs.jsonl", dict(run_id=name, status=status,
                                    merge_seconds=result.get("merge_seconds")))
    return result


def stage_cells(stage):
    cells = []
    rows = "rewrite_rows"
    columns = "rewrite_columns"
    if stage == "correctness":
        cells = [(name, variant, rows, 0) for name in (
            "tiny", "condition_overlap", "condition_reject", "string_null")
            for variant in ("U_main", "K")]
    elif stage == "smoke":
        for name in ("Wn", "Ws", "F16", "dense_safe", "R"):
            cells += [(name, "U_main", rows, 0), (name, "K", rows, 0)]
            if name != "R":
                cells.append((name, "K", columns, 0))
    elif stage == "pairs":
        rng = random.Random(951819)
        for block in range(1, 4):
            for name in ("F16", "Wn", "Ws"):
                order = [("U_main", rows), ("K", rows), ("K", columns)]
                rng.shuffle(order)
                cells += [(name, variant, mode, block) for variant, mode in order]
    return cells


def summarize():
    observed = records()
    pairs = []
    for name in ("F16", "Wn", "Ws"):
        for top, bottom in (("K/rewrite_rows", "U_main/rewrite_rows"),
                            ("K/rewrite_columns", "K/rewrite_rows")):
            ratios = []
            for block in range(1, 4):
                group = {f'{row["variant"]}/{row["write_mode"]}': row for row in observed
                         if row["stage"] == "pairs" and row["workload"] == name
                         and row["block"] == block and row["status"] == "validated_success"}
                if top in group and bottom in group:
                    ratios.append(dict(block=block, ratio=group[top]["merge_seconds"] /
                                       group[bottom]["merge_seconds"]))
            pairs.append(dict(workload=name, comparison=f"{top} / {bottom}", planned_pairs=3,
                              valid_pairs=len(ratios), ratios=ratios,
                              median_ratio=statistics.median(row["ratio"] for row in ratios)
                              if ratios else None))
    summary = dict(scope="Current-main/K local hot-cache API execution; separate from historical C",
                   configured_pool_bytes=POOL, cgroup_limit_bytes=LIMIT,
                   pool_enforcement="U_main may use an unbounded pool; configuration alone is not proof",
                   results=[{key: row.get(key) for key in (
                       "run_id", "stage", "block", "workload", "variant", "write_mode",
                       "status", "merge_seconds", "cpu_seconds", "new_data_file_bytes",
                       "sampled_peak_rss_bytes", "cgroup_peak_bytes")} for row in observed],
                   paired_comparisons=pairs,
                   inherited_failures=[json.loads(path.read_text()) for path in
                       sorted((ROOT / "references").glob("*.json"))])
    save(ROOT / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--baseline", required=True, type=Path)
    init.add_argument("--candidate", required=True, type=Path)
    init.add_argument("--base-commit", required=True)
    init.add_argument("--cgroup", required=True, type=Path)
    init.add_argument("--prior-failure-root", required=True, type=Path)
    init.add_argument("--build-log", action="append", default=[])
    for name in ("freeze", "generate", "import-fixtures", "identity", "summarize"):
        sub.add_parser(name)
    run = sub.add_parser("run")
    run.add_argument("stage", choices=("correctness", "smoke", "pairs"))
    worker = sub.add_parser("worker")
    worker.add_argument("operation", choices=("execute", "validate", "validate_unchanged", "generate"))
    worker.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.action == "identity":
        sys.stdout.write(json.dumps(identity()) + "\n")
        return
    if args.action == "worker":
        spec = json.loads((args.directory / "spec.json").read_text())
        if args.operation == "execute":
            execute(spec, args.directory)
        elif args.operation == "generate":
            fixtures.generate(spec, ROOT / "fixtures" / spec["name"])
        else:
            result = fixtures.validate(spec, args.directory,
                                       unchanged=args.operation == "validate_unchanged")
            save(args.directory / f"{args.operation}.json", result)
        return
    with (ROOT / ".coordinator.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "init":
            if (ROOT / "config.json").exists():
                raise FileExistsError(ROOT / "config.json")
            args.cgroup.mkdir(exist_ok=True)
            build_logs = dict(value.split("=", 1) for value in args.build_log)
            assert set(build_logs) == {"U_main", "K"}, "Both optimized build logs are required"
            cfg = dict(checkouts={"U_main": str(args.baseline.resolve()),
                                  "K": str(args.candidate.resolve())},
                       base_commit=args.base_commit, cgroup=str(args.cgroup.resolve()),
                       prior_failure_root=str(args.prior_failure_root.resolve()),
                       uv=shutil.which("uv"), build_logs=build_logs)
            assert cfg["uv"], "uv must be available through the documented environment"
            save(ROOT / "config.json", cfg)
        elif args.action == "freeze":
            if (ROOT / "freeze.json").exists():
                raise FileExistsError(ROOT / "freeze.json")
            frozen = current_freeze()
            for variant in ("U_main", "K"):
                assert frozen["identities"][variant]["tree"]["head"] == config()["base_commit"]
            assert not frozen["identities"]["U_main"]["tree"]["tracked_status"]
            save(ROOT / "freeze.json", frozen)
        elif args.action == "generate":
            verify_freeze()
            (ROOT / "fixtures").mkdir(exist_ok=True)
            for name, spec in fixtures.workloads().items():
                directory = ROOT / "setup" / name
                directory.mkdir(parents=True, exist_ok=False)
                save(directory / "spec.json", spec)
                result = isolated("generate", "U_main", directory)
                if result["exit_code"] != 0:
                    raise RuntimeError(f"Fixture generation failed: {name}")
            save(ROOT / "fixture-hashes.json", {str(path.relative_to(ROOT)): digest(path)
                 for path in sorted((ROOT / "fixtures").rglob("*")) if path.is_file()})
        elif args.action == "import-fixtures":
            import_fixtures(verify_freeze())
            verify_freeze()
        elif args.action == "run":
            frozen = verify_freeze()
            hashes = json.loads((ROOT / "fixture-hashes.json").read_text())
            assert hashes == frozen["prior_failure"]["fixture_hashes"], \
                "Fixtures must match the inherited failure; import the frozen prior fixtures"
            verify_fixture_files(ROOT, hashes)
            required = "correctness" if args.stage == "smoke" else "smoke" if args.stage == "pairs" else None
            if required:
                gate = json.loads((ROOT / f"gate-{required}.json").read_text())
                assert gate["complete"] and gate["candidate_passed"], gate
            cells = stage_cells(args.stage)
            save(ROOT / f"plan-{args.stage}.json", cells)
            completed = []
            for name, variant, mode, block in cells:
                result = run_cell(args.stage, name, variant, mode, block)
                completed.append(result)
                accepted = result["status"] == "validated_success"
                baseline_resource = args.stage != "correctness" and variant == "U_main" and result["status"] in (
                    "confirmed_oom", "resource_exhausted", "not_repeated_after_resource_failure")
                gate = dict(stage=args.stage, planned=len(cells), completed=len(completed),
                            complete=len(completed) == len(cells),
                            candidate_passed=all(row["status"] == "validated_success"
                                for row in completed if row["variant"] == "K"),
                            statuses=[dict(run_id=row["run_id"], status=row["status"],
                                           executed=row.get("executed", True),
                                           prior_run_id=row.get("prior_run_id"))
                                      for row in completed])
                save(ROOT / f"gate-{args.stage}.json", gate)
                if not accepted and not baseline_resource:
                    summarize()
                    raise RuntimeError(f'{result["run_id"]}: {result["status"]}')
            verify_freeze()
            summarize()
        else:
            verify_freeze()
            summarize()


if __name__ == "__main__":
    main()
