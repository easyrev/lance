"""Read-only audit of the completed final merge matrix; Python standard library only.

Run from a prepared checkout's python/ directory using its documented uv setup:
  uv run --no-sync python /path/to/audit-results.py --root /path/to/results --live

For an evidence mirror without checkouts or datasets, omit --live and use
--prior-root /path/to/killer-merge-validation to locate the old evidence mirror.
Artifact-only success does not verify current source, extension or dataset files.
This script does not import Lance, call the harness, build, or run a benchmark.
It writes JSON to stdout and exits nonzero on the first inconsistent assertion.
"""

import argparse
import hashlib
import json
import math
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


POOL = 1 << 30
LIMIT = 8 << 30
PRIOR_RUN = "smoke-F16-U_main-rewrite_rows-b0"
SUMMARY_KEYS = (
    "run_id", "stage", "block", "workload", "variant", "write_mode", "status",
    "merge_seconds", "cpu_seconds", "new_data_file_bytes", "sampled_peak_rss_bytes",
    "cgroup_peak_bytes",
)
MEASURES = (
    "merge_seconds", "cpu_seconds", "new_data_file_bytes", "new_data_file_count",
    "sampled_peak_rss_bytes", "cgroup_peak_bytes",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def counters(text):
    return {name: int(value) for name, value in (line.split() for line in text.splitlines())}


def matrix():
    rows, columns = "rewrite_rows", "rewrite_columns"
    stages = {
        "correctness": [[name, variant, rows, 0] for name in (
            "tiny", "condition_overlap", "condition_reject", "string_null")
            for variant in ("U_main", "K")],
        "smoke": [], "pairs": [],
    }
    for name in ("Wn", "Ws", "F16", "dense_safe", "R"):
        stages["smoke"] += [[name, "U_main", rows, 0], [name, "K", rows, 0]]
        if name != "R":
            stages["smoke"].append([name, "K", columns, 0])
    rng = random.Random(951819)
    for block in range(1, 4):
        for name in ("F16", "Wn", "Ws"):
            order = [("U_main", rows), ("K", rows), ("K", columns)]
            rng.shuffle(order)
            stages["pairs"] += [[name, variant, mode, block] for variant, mode in order]
    return stages


def cell_id(stage, cell):
    name, variant, mode, block = cell
    return f"{stage}-{name}-{variant}-{mode}-b{block}"


def check_resources(resources, operation, variant, run_id, oom=False):
    label = f"{run_id}/{operation}"
    require(resources["operation"] == operation and resources["variant"] == variant, label)
    require(resources["configured_pool_bytes"] == POOL, f"{label}: pool configuration")
    require(not resources["timeout"] and "cleanup_error" not in resources, f"{label}: worker cleanup")
    require(resources["exit_code"] == (-9 if oom else 0), f"{label}: exit code")
    require(resources["confirmed_oom"] == oom, f"{label}: OOM classification")
    command = resources["command"]
    require(command[-3:-1] == ["worker", operation], f"{label}: worker invocation")
    require(Path(command[-1]).name == run_id and Path(command[-1]).parent.name == "runs", label)
    for moment in ("before", "after"):
        require(int(resources[moment]["memory.max"]) == LIMIT, f"{label}: cgroup limit")
        require(int(resources[moment]["memory.swap.max"]) == 0, f"{label}: swap limit")
    before, after = resources["before"], resources["after"]
    require(counters(before["cgroup.events"])["populated"] == 0, f"{label}: initial population")
    oom_delta = counters(after["memory.events"])["oom_kill"] - counters(before["memory.events"])["oom_kill"]
    require(oom_delta > 0 if oom else oom_delta == 0, f"{label}: OOM event delta")


def fields(spec):
    if spec.get("small_string"):
        return {"id", "value", "keep", "guard", "row_marker"}
    names = {"id", *(f"c{i}" for i in range(spec["columns"] - 1))}
    if spec["binary"]:
        names |= {"payload", "new_payload", "row_marker"}
    return names


def expected_counts(name):
    updates = {"tiny": 4, "F16": 100, "Wn": 25, "Ws": 25, "R": 100_000,
               "dense_safe": 360, "condition_overlap": 8, "condition_reject": 0,
               "string_null": 2}
    return dict(num_updated_rows=updates[name], num_inserted_rows=2_900_000 if name == "R" else 0,
                num_deleted_rows=0)


def verify_files(root, manifest):
    actual = {str(path.relative_to(root)) for path in (root / "fixtures").rglob("*")
              if path.is_file()}
    require(actual == set(manifest), f"{root}: fixture file set")
    for relative, expected in manifest.items():
        require(digest(root / relative) == expected, f"{root / relative}: fixture hash")


def verify_live_tree(path, expected):
    def git(*args):
        return subprocess.check_output(["git", "--no-optional-locks", "-C", str(path), *args])

    require(git("rev-parse", "HEAD").decode().strip() == expected["head"], f"{path}: HEAD")
    require(git("status", "--porcelain", "--untracked-files=no").decode() == expected["tracked_status"],
            f"{path}: tracked status")
    require(hashlib.sha256(git("diff", "HEAD", "--binary")).hexdigest() == expected["diff_sha256"],
            f"{path}: tracked diff")
    names = set(git("ls-files", "-z").decode().split("\0"))
    names |= set(git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0"))
    selected = {name for name in names if name and (
        name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "python/Makefile") or
        (name.startswith(("rust/", "python/", ".cargo/")) and
         Path(name).suffix in (".rs", ".py", ".toml", ".lock", ".mk"))) and (path / name).is_file()}
    require(selected == set(expected["source_hashes"]), f"{path}: source file set")
    for name, sha in expected["source_hashes"].items():
        require(digest(path / name) == sha, f"{path / name}: source hash")


def audit(args):
    root = args.root.resolve()
    frozen = read(root / "freeze.json")
    cfg, specs = frozen["config"], frozen["workloads"]
    require(read(root / "config.json") == cfg, "Current config differs from freeze")
    require(set(specs) == {"tiny", "F16", "Wn", "Ws", "R", "dense_safe", "condition_overlap",
                           "condition_reject", "string_null"}, "Workload set")
    for name, sha in frozen["harness"].items():
        require(digest(root / name) == sha, f"{name}: frozen harness hash")
    for variant, identity in frozen["identities"].items():
        require(identity["tree"]["head"] == cfg["base_commit"], f"{variant}: base commit")
    require(frozen["identities"]["U_main"]["tree"]["tracked_status"] == "", "Baseline has tracked changes")
    prior = frozen["prior_failure"]
    prior_root = args.prior_root.resolve() if args.prior_root else Path(prior["source_root"])
    prior_data = {}
    for name, item in prior["artifacts"].items():
        relative = Path(item["path"]).relative_to(Path(prior["source_root"]))
        path = prior_root / relative
        require(digest(path) == item["sha256"], f"{path}: inherited artifact hash")
        prior_data[name] = read(path)
    require(prior["run_id"] == PRIOR_RUN and prior["status"] == "confirmed_oom", "Inherited run")
    require(prior["configured_pool_bytes"] == POOL and prior["cgroup_limit_bytes"] == LIMIT
            and prior["swap_limit_bytes"] == 0, "Inherited limits")
    require(prior_data["freeze"]["identities"]["U_main"] == frozen["identities"]["U_main"],
            "Inherited baseline identity differs")
    require(prior_data["freeze"]["workloads"] == specs, "Inherited workload definitions differ")
    require(prior_data["freeze"]["build_environment"] == frozen["build_environment"], "Inherited environment")
    require(prior_data["freeze"]["build_logs"]["U_main"]["sha256"] ==
            frozen["build_logs"]["U_main"]["sha256"], "Inherited baseline build log")
    for name, sha in prior_data["freeze"]["harness"].items():
        require(digest(prior_root / name) == sha, f"Prior {name}: frozen harness hash")
    require(prior_data["freeze"]["harness"]["fixtures.py"] == frozen["harness"]["fixtures.py"],
            "Oracle or fixture generator changed")
    manifest = read(root / "fixture-hashes.json")
    require(manifest == prior["fixture_hashes"] == prior_data["fixture_hashes"], "Fixture manifests differ")
    require({Path(name).parts[1] for name in manifest} == set(specs), "Fixture manifest workload set")
    imported = read(root / "fixture-import.json")
    require(imported["source_manifest"] == prior["artifacts"]["fixture_hashes"] and
            imported["files"] == len(manifest) and set(imported["workloads"]) == set(specs), "Fixture import record")
    prior_result, prior_metrics = prior_data["result"], prior_data["metrics"]
    require(prior_result["run_id"] == PRIOR_RUN and prior_result["status"] == "confirmed_oom", "Prior result")
    require(prior_result["snapshot"] == prior_metrics["snapshot"] == prior["snapshot"] == 1, "Prior snapshot")
    require(prior_result["identity"] == prior_metrics["identity"] == frozen["identities"]["U_main"]["imported"],
            "Prior worker imported identity")
    require(prior_data["spec"] == specs["F16"] | dict(write_mode="rewrite_rows"), "Prior spec")
    require(prior_result["execution"] == prior_data["execute-resources"], "Prior execution resources")
    check_resources(prior_data["execute-resources"], "execute", "U_main", PRIOR_RUN, oom=True)
    check_resources(prior_data["validate_unchanged-resources"], "validate_unchanged", "U_main", PRIOR_RUN)
    prior_oracle = prior_data["validate_unchanged"]
    require(prior_oracle["validated"] and prior_oracle["unchanged"] and prior_oracle["version"] == 1
            and prior_oracle["rows"] == 16_000_000 and set(prior_oracle["hashes"]) == fields(specs["F16"])
            and prior_oracle["expected_counts"] == dict(num_updated_rows=0, num_inserted_rows=0, num_deleted_rows=0),
            "Prior unchanged full-field oracle")

    stages = matrix()
    cells = {cell_id(stage, cell): (stage, cell) for stage, planned in stages.items() for cell in planned}
    reference_ids = {name for name, (_, cell) in cells.items()
                     if cell[0:3] == ["F16", "U_main", "rewrite_rows"]}
    actual_ids = set(cells) - reference_ids
    records = {path.parent.name: read(path) for path in sorted((root / "runs").glob("*/result.json"))}
    references = {path.stem: read(path) for path in sorted((root / "references").glob("*.json"))}
    require(len(cells) == 49 and len(actual_ids) == 45 and len(reference_ids) == 4, "Planned matrix dimensions")
    require(set(records) == actual_ids, f"Actual run IDs: missing={sorted(actual_ids - set(records))}, extra={sorted(set(records) - actual_ids)}")
    require(set(references) == reference_ids, "Inherited reference IDs")
    require(not any((root / "runs" / name).exists() for name in reference_ids), "A reference has a run directory")
    for name, row in references.items():
        stage, (workload, variant, mode, block) = cells[name]
        require(all(row[key] == value for key, value in dict(
            run_id=name, stage=stage, workload=workload, variant=variant, write_mode=mode, block=block,
            status="not_repeated_after_resource_failure", executed=False, prior_run_id=PRIOR_RUN,
            configured_pool_bytes=POOL, cgroup_limit_bytes=LIMIT).items()), f"{name}: reference metadata")
        require(row["prior_artifacts"] == prior["artifacts"] and row["prior_extension_sha256"] ==
                frozen["identities"]["U_main"]["imported"]["extension_sha256"], f"{name}: inherited evidence")
        require("merge_seconds" not in row, f"{name}: reference contains a timing sample")

    for name, row in records.items():
        stage, (workload, variant, mode, block) = cells[name]
        directory = root / "runs" / name
        spec = specs[workload] | dict(write_mode=mode)
        require(read(directory / "spec.json") == spec, f"{name}: spec")
        require(all(row[key] == value for key, value in dict(
            run_id=name, stage=stage, workload=workload, variant=variant, write_mode=mode, block=block,
            status="validated_success", snapshot=1, configured_pool_bytes=POOL).items()), f"{name}: result metadata")
        require(row["identity"] == frozen["identities"][variant]["imported"], f"{name}: worker identity")
        metrics = read(directory / "metrics.json")
        require(metrics["status"] == "execute_returned", f"{name}: execution did not return")
        require(all(row[key] == value for key, value in metrics.items() if key != "status"), f"{name}: metrics/result divergence")
        execution = read(directory / "execute-resources.json")
        require(row["execution"] == execution, f"{name}: execution resource divergence")
        check_resources(execution, "execute", variant, name)
        check_resources(read(directory / "validate-resources.json"), "validate", "U_main", name)
        oracle = read(directory / "validate.json")
        counts = expected_counts(workload)
        expected_rows = max(spec["rows"], spec["source_rows"]) if spec["full"] else spec["rows"]
        require(oracle["validated"] and oracle["rows"] == expected_rows, f"{name}: oracle row count")
        require(oracle["expected_counts"] == row["merge_stats"] == counts, f"{name}: action counts")
        require(oracle["version"] > row["snapshot"] if any(counts.values()) else
                oracle["version"] >= row["snapshot"], f"{name}: post-execution version")
        if spec.get("small_string"):
            require(oracle["oracle"] == "all-fields-string-null", f"{name}: nullable-string oracle")
        else:
            require(oracle["oracle"] == "splitmix64-v1-all-fields" and not oracle["unchanged"]
                    and set(oracle["hashes"]) == fields(spec), f"{name}: full-field oracle")
        samples = [json.loads(line) for line in (directory / "execute-memory.jsonl").read_text().splitlines()]
        require(samples, f"{name}: no resource samples")
        require(row["sampled_peak_rss_bytes"] == max(sample.get("VmRSS", 0) for sample in samples), f"{name}: sampled RSS")
        require(row["cgroup_peak_bytes"] == int(execution["after"]["memory.peak"]), f"{name}: cgroup peak")
        require(max(sample["cgroup_peak"] for sample in samples) <= row["cgroup_peak_bytes"], f"{name}: sampled cgroup peak")
        if not spec.get("small_string"):
            producer = [json.loads(line) for line in (directory / "producer.jsonl").read_text().splitlines()]
            require(sum(batch["rows"] for batch in producer) == spec["source_rows"], f"{name}: produced source rows")
        require(all(math.isfinite(row[key]) and row[key] >= 0 for key in MEASURES), f"{name}: invalid metric")
        require(row["merge_seconds"] > 0, f"{name}: zero elapsed time")
        if args.live:
            fixture_data = {str(path.relative_to(root / "fixtures" / workload))
                            for path in (root / "fixtures" / workload).rglob("*.lance")}
            added = [path for path in (directory / "dataset").rglob("*.lance")
                     if str(path.relative_to(directory / "dataset")) not in fixture_data]
            require(len(added) == row["new_data_file_count"] and
                    sum(path.stat().st_size for path in added) == row["new_data_file_bytes"], f"{name}: new data files")

    for stage, planned in stages.items():
        require(read(root / f"plan-{stage}.json") == planned, f"{stage}: randomized plan")
        gate = read(root / f"gate-{stage}.json")
        require(gate["complete"] and gate["candidate_passed"] and gate["stage"] == stage
                and gate["planned"] == gate["completed"] == len(planned), f"{stage}: gate")
        expected = [dict(run_id=cell_id(stage, cell),
                         status="not_repeated_after_resource_failure" if cell_id(stage, cell) in reference_ids else "validated_success",
                         executed=cell_id(stage, cell) not in reference_ids,
                         prior_run_id=PRIOR_RUN if cell_id(stage, cell) in reference_ids else None)
                    for cell in planned]
        require(gate["statuses"] == expected, f"{stage}: gate status set/order")

    summary = read(root / "summary.json")
    require(summary["configured_pool_bytes"] == POOL and summary["cgroup_limit_bytes"] == LIMIT, "Summary limits")
    require(summary["results"] == [{key: row.get(key) for key in SUMMARY_KEYS} for row in records.values()], "Summary results")
    require(summary["inherited_failures"] == list(references.values()), "Summary references")
    pairs = []
    comparisons = []
    for workload in ("F16", "Wn", "Ws"):
        for top, bottom in (("K/rewrite_rows", "U_main/rewrite_rows"), ("K/rewrite_columns", "K/rewrite_rows")):
            ratios, numerators, denominators = [], [], []
            for block in range(1, 4):
                group = {f'{row["variant"]}/{row["write_mode"]}': row for row in records.values()
                         if row["stage"] == "pairs" and row["workload"] == workload and row["block"] == block}
                if top in group and bottom in group:
                    numerators.append(group[top]["merge_seconds"])
                    denominators.append(group[bottom]["merge_seconds"])
                    ratios.append(dict(block=block, ratio=numerators[-1] / denominators[-1]))
            median = statistics.median(item["ratio"] for item in ratios) if ratios else None
            entry = dict(workload=workload, comparison=f"{top} / {bottom}", planned_pairs=3,
                         valid_pairs=len(ratios), ratios=ratios, median_ratio=median)
            pairs.append(entry)
            comparisons.append(entry | dict(ratio_of_medians=statistics.median(numerators) /
                                            statistics.median(denominators) if ratios else None))
    require(summary["paired_comparisons"] == pairs, "Same-block ratios differ from raw results")
    distributions = []
    groups = defaultdict(list)
    for row in records.values():
        groups[(row["stage"], row["workload"], row["variant"], row["write_mode"])].append(row)
    for (stage, workload, variant, mode), group in sorted(groups.items()):
        measures = {key: dict(median=statistics.median(row[key] for row in group),
                             minimum=min(row[key] for row in group), maximum=max(row[key] for row in group))
                    for key in MEASURES}
        distributions.append(dict(stage=stage, workload=workload, variant=variant, write_mode=mode,
                                  n=len(group), run_ids=[row["run_id"] for row in group], measures=measures))

    if args.live:
        for variant, identity in frozen["identities"].items():
            verify_live_tree(Path(cfg["checkouts"][variant]), identity["tree"])
            require(digest(identity["imported"]["extension"]) == identity["imported"]["extension_sha256"],
                    f"{variant}: current extension hash")
        for name, item in frozen["build_logs"].items():
            require(digest(item["path"]) == item["sha256"], f"{name}: current build log")
        verify_files(root, manifest)
        verify_files(prior_root, manifest)
        for name, spec in specs.items():
            metadata = read(root / "fixtures" / name / "fixture.json")
            fragments = (spec["rows"] + spec["fragment_rows"] - 1) // spec["fragment_rows"]
            require(metadata == dict(spec=spec, rows=spec["rows"], fragments=fragments, version=1), f"{name}: fixture metadata")

    return dict(status="passed", mode="live-files-and-artifacts" if args.live else "artifacts-only",
                result_root=str(root), freeze_sha256=digest(root / "freeze.json"),
                audit_script_sha256=digest(Path(__file__)), planned_cells=49, new_executions=45,
                new_validated_successes=45, independent_oracles=45, inherited_references=4,
                historical_resource_failures=1, fixture_count=9, fixture_files=len(manifest),
                live_source_binary_fixture_hashes_verified=args.live,
                paired_comparisons=comparisons, distributions=distributions,
                limitations=[
                    "The 1 GiB pool is configured; it is not a total RSS limit or proof of U_main pool enforcement.",
                    "Four F16/U_main references represent one old OOM; there is no new F16 baseline timing or speedup.",
                    "New .lance file bytes exclude manifests, deletion files, transient writes and future maintenance.",
                    "RSS samples and cgroup charged memory are separate measures; neither is an allocation attribution.",
                    "An oracle artifact records a completed separate validation; this audit does not rescan dataset values.",
                    "Frozen source, extension and build logs establish identity, not an independent build attestation.",
                ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--prior-root", type=Path, help="Read-only local mirror of the original evidence root")
    parser.add_argument("--live", action="store_true", help="Also hash current checkouts, binaries, fixtures and new data files")
    args = parser.parse_args()
    try:
        result = audit(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        json.dump(dict(status="failed", error=str(error), result_root=str(args.root.resolve()),
                       audit_script_sha256=digest(Path(__file__))), sys.stdout, indent=2)
        sys.stdout.write("\n")
        raise SystemExit(1) from error
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
