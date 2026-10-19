"""Audit frozen experiment records without importing Lance or running a workload.

Run from a repository-prepared Python environment with uv run --no-sync python.
Default mode audits recorded evidence and the local frozen harness. --verify-files
also hashes live source, extensions, build logs and fixture files on their host.
It never re-executes the row oracle. Its success describes evidence consistency,
not universal correctness, candidate survival, or an independently rerun oracle.
"""

import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys


GIB = 1 << 30
SUCCESS = "validated_success"
DIAGNOSTIC = "validated_diagnostic"
RESOURCE_FAILURES = {"confirmed_oom", "resource_exhausted"}
REFERENCE = "not_repeated_after_resource_failure"
CORRECTNESS = {"tiny", "string_null", "condition_overlap", "condition_reject"}


def read(path):
    return json.loads(Path(path).read_text())


def sha256(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def check(condition, message):
    if not condition:
        raise ValueError(message)


def hash_value(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def content_identity(identity):
    return dict(source_hashes=identity["tree"]["source_hashes"], imported={
        key: value for key, value in identity["imported"].items() if key not in ("module", "extension")})


def execution_context(frozen, variant):
    cfg = frozen["config"]
    validator = cfg["validator"]
    return dict(harness=frozen["harness"], host=frozen["host"], environment=frozen["process_environment"],
                common_config={key: value for key, value in cfg.items() if key != "variants"},
                variants={label: cfg["variants"][label] for label in {variant, validator}},
                validator_identity=content_identity(frozen["identities"][validator]))


def contract(cell, frozen, manifest):
    return dict(cell={key: value for key, value in cell.items() if key not in ("block", "run_id")},
                identity=content_identity(frozen["identities"][cell["variant"]]),
                fixture_files=manifest["files"], spec=manifest["metadata"]["spec"],
                variant_environment=frozen["config"]["variants"][cell["variant"]].get("environment", {}))


def fields(spec):
    if spec.get("small_string"):
        return ["id", "value", "keep", "guard", "row_marker"]
    if spec.get("variable_payload"):
        return ["id", "c0", "c1", "keep_text", "keep_binary", "row_marker"]
    return ["id", *(f"c{i}" for i in range(spec["columns"] - 1)),
            *(["payload", "new_payload", "row_marker"] if spec["binary"] else [])]


def expected_counts(spec, unchanged):
    if unchanged:
        updated = inserted = 0
    elif spec.get("small_string"):
        updated, inserted = 2, 0
    elif spec.get("reject_all"):
        updated = inserted = 0
    elif spec["full"]:
        updated = min(spec["rows"], spec["source_rows"])
        inserted = max(0, spec["source_rows"] - spec["rows"])
    elif spec["dense"]:
        prefix = spec["rows"] * 9 // 10
        updated = sum(prefix // 5 + (key < prefix % 5) for key in range(min(5, spec["source_rows"])))
        updated += max(0, min(spec["rows"], spec["source_rows"] - 100) - prefix)
        inserted = 0
    elif spec.get("predicate_modulus"):
        check(spec["source_rows"] == spec["rows"], "Unsupported sparse predicate oracle specification")
        updated = (spec["rows"] + spec["predicate_modulus"] - 1) // spec["predicate_modulus"]
        inserted = 0
    else:
        check(spec["source_rows"] <= spec["rows"], "Partial unique-key source exceeds target")
        updated, inserted = spec["source_rows"], 0
    return dict(num_updated_rows=updated, num_inserted_rows=inserted, num_deleted_rows=0)


def producer(directory):
    records, truncated = [], False
    path = directory / "producer.jsonl"
    lines = path.read_text().splitlines() if path.exists() else []
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            check(index == len(lines) - 1, "Producer corruption before final line")
            truncated = True
            continue
        check(isinstance(record["rows"], int) and record["rows"] > 0, "Invalid producer row count")
        check(isinstance(record["bytes"], int) and record["bytes"] >= 0, "Invalid producer byte count")
        records.append(record)
    return dict(yielded_batches=len(records), yielded_rows=sum(row["rows"] for row in records),
                yielded_arrow_bytes=sum(row["bytes"] for row in records), truncated_final_record=truncated)


def key_values(text):
    return {key: int(value) for key, value in (line.split() for line in text.splitlines())}


def summarize_numbers(values):
    return dict(n=len(values), minimum=min(values), median=statistics.median(values), maximum=max(values))


class Audit:
    def __init__(self, root, verify_files, allow_incomplete):
        self.root, self.verify_files, self.allow_incomplete = root, verify_files, allow_incomplete
        self.errors, self.warnings = [], []
        self.freezes, self.plans, self.planned, self.actual, self.diagnostics, self.references = {}, {}, {}, {}, {}, {}
        self.verified, self.contexts, self.resource_paths = {}, {}, set()
        self.hash_cache = {}
        self.starts, self.ends, self.event_statuses = {}, {}, {}

    def guarded(self, label, function, *arguments):
        try:
            return function(*arguments)
        except (AssertionError, IndexError, KeyError, TypeError, ValueError, OSError) as error:
            self.errors.append(dict(artifact=label, error=f"{type(error).__name__}: {error}"))
            return None

    def verify_hash(self, path, expected):
        check(re.fullmatch(r"[0-9a-f]{64}", expected) is not None, f"Invalid SHA256: {path}")
        path = Path(path)
        if path not in self.hash_cache:
            self.hash_cache[path] = sha256(path)
        check(self.hash_cache[path] == expected, f"SHA256 mismatch: {path}")

    def freeze(self, path):
        value = read(path)
        check(set(value["labels"]) == set(value["identities"]) == set(value["config"]["variants"]), "Freeze label mismatch")
        current = read(self.root / "config.json")
        check({key: item for key, item in current.items() if key != "variants"} ==
              {key: item for key, item in value["config"].items() if key != "variants"}, "Common configuration differs from freeze")
        check(all(current["variants"][label] == value["config"]["variants"][label] for label in value["labels"]), "Selected variant configuration differs from freeze")
        for name, expected in value["harness"].items():
            self.verify_hash(self.root / "harness" / name, expected)
        for label, identity in value["identities"].items():
            cfg = value["config"]["variants"][label]
            check(identity["pool_policy"]["source_review"] == cfg["pool_policy"], "Pool review/config differs")
            for name, expected in identity["pool_policy"]["source_hashes"].items():
                check(identity["tree"]["source_hashes"][name] == expected, f"Pool source hash differs: {label}/{name}")
            check(set(identity["pool_policy"]["source_hashes"]) == set(cfg["pool_source_files"]), "Pool source file set differs")
            for name, expected in identity["tree"]["source_hashes"].items():
                check(re.fullmatch(r"[0-9a-f]{64}", expected) is not None, f"Invalid source hash: {label}/{name}")
                if self.verify_files:
                    self.verify_hash(Path(cfg["checkout"]) / name, expected)
            extension = identity["imported"]
            check(re.fullmatch(r"[0-9a-f]{64}", extension["extension_sha256"]) is not None, "Invalid extension SHA")
            check(Path(extension["extension"]).is_relative_to(Path(cfg["checkout"])), "Extension outside frozen checkout")
            check(Path(extension["module"]).is_relative_to(Path(cfg["checkout"])), "Module outside frozen checkout")
            if self.verify_files:
                self.verify_hash(extension["extension"], extension["extension_sha256"])
                self.verify_hash(value["build_logs"][label]["path"], value["build_logs"][label]["sha256"])
        self.freezes[path.stem] = value

    def plan(self, path):
        plan = read(path)
        check(plan["name"] == path.stem, "Plan filename differs from name")
        frozen = self.freezes[plan["freeze"]]
        self.verify_hash(self.root / "freezes" / f'{plan["freeze"]}.json', plan["freeze_sha256"])
        check(set(plan["workloads"]) == set(plan["fixtures"]), "Plan workload/fixture sets differ")
        for name, manifest in plan["fixtures"].items():
            check(read(self.root / "fixture-manifests" / f"{name}.json") == manifest, f"Fixture manifest changed: {name}")
            spec, metadata = manifest["metadata"]["spec"], manifest["metadata"]
            check(spec == frozen["workloads"][name], f"Fixture spec differs from freeze: {name}")
            check(metadata["rows"] == spec["rows"] and metadata["version"] == 1, "Fixture row count/snapshot differs")
            check(metadata["fragments"] == math.ceil(spec["rows"] / spec["fragment_rows"]), "Fixture fragment count differs")
            for relative, expected in manifest["files"].items():
                check(not Path(relative).is_absolute() and ".." not in Path(relative).parts, "Unsafe fixture path")
                check(re.fullmatch(r"[0-9a-f]{64}", expected) is not None, "Invalid fixture hash")
            if self.verify_files:
                folder = self.root / "fixtures" / name
                check({str(item.relative_to(folder)) for item in folder.rglob("*") if item.is_file()} == set(manifest["files"]), "Fixture file set differs")
                for relative, expected in manifest["files"].items():
                    self.verify_hash(folder / relative, expected)
            origin = manifest["origin"]
            if origin["kind"] == "generated":
                self.verify_hash(self.root / "freezes" / f'{origin["freeze"]}.json', origin["freeze_sha256"])
                generated_freeze = self.freezes[origin["freeze"]]
                check(origin["generator_identity"] == generated_freeze["identities"][generated_freeze["config"]["validator"]]["imported"], "Generator identity differs")
                setup = self.root / "setup" / name
                generated = read(setup / "generate.json")
                check(generated["generated"] is True and generated["identity"] == origin["generator_identity"], "Actual generator identity differs")
                check(read(setup / "spec.json") == spec, "Generator spec differs")
                generation = read(setup / "generate-resources.json")
                check(generation["exit_code"] == 0 and not generation["timeout"] and not generation["confirmed_oom"] and "cleanup_error" not in generation, "Fixture generation did not complete cleanly")
            elif origin["kind"] == "import":
                for key in ("source_freeze_sha256", "source_manifest_sha256", "source_generator_sha256"):
                    check(re.fullmatch(r"[0-9a-f]{64}", origin[key]) is not None, "Invalid imported fixture provenance hash")
                if self.verify_files:
                    old_root = Path(origin["source_root"])
                    self.verify_hash(old_root / "freeze.json", origin["source_freeze_sha256"])
                    self.verify_hash(old_root / "fixture-hashes.json", origin["source_manifest_sha256"])
                    self.verify_hash(old_root / "fixtures.py", origin["source_generator_sha256"])
                    old_freeze = read(old_root / "freeze.json")
                    check(old_freeze["harness"]["fixtures.py"] == origin["source_generator_sha256"] and old_freeze["workloads"][name] == spec, "Imported generator/spec differs from historical freeze")
                    prefix = Path("fixtures") / name
                    old_files = {str(Path(relative).relative_to(prefix)): sha for relative, sha in read(old_root / "fixture-hashes.json").items() if Path(relative).is_relative_to(prefix)}
                    check(old_files == manifest["files"], "Imported fixture file hashes differ from historical manifest")
            else:
                raise ValueError(f'Unknown fixture origin: {origin["kind"]}')
        for cell in plan["cells"]:
            identifier = cell["run_id"]
            check(identifier not in self.planned, f"Duplicate planned run: {identifier}")
            check(cell["workload"] in plan["fixtures"] and cell["variant"] in frozen["labels"], "Unknown workload/variant")
            check(cell["block"] in ((1, 2, 3) if plan["kind"] == "pairs" else (0,)), "Unexpected block")
            check(identifier == f'{plan["name"]}-{cell["workload"]}-{cell["variant"]}-{cell["write_mode"]}-b{cell["block"]}', "Run ID differs from cell")
            check(cell["pool_bytes"] > 0 and cell["cgroup_bytes"] > 0 and cell["timeout_seconds"] > 0, "Nonpositive resource limit")
            check(cell["cache"] in ("hot", "evict_attempt") and cell["input_form"] in ("reader", "materialized"), "Unknown cache/input form")
            check(cell["write_mode"] in ("rewrite_rows", "rewrite_columns"), "Unknown writer mode")
            self.planned[identifier] = (plan, cell, frozen)
            self.contexts[identifier] = execution_context(frozen, cell["variant"])
        if plan["kind"] == "pairs":
            check(plan["comparisons"], "Pairs have no registered comparison")
            sets = [{(cell["workload"], cell["variant"], cell["write_mode"]) for cell in plan["cells"] if cell["block"] == block}
                    for block in (1, 2, 3)]
            check(sets[0] and sets[0] == sets[1] == sets[2], "Pair block cell sets differ")
            for name in plan["workloads"]:
                choices = {f'{cell["variant"]}/{cell["write_mode"]}' for cell in plan["cells"] if cell["workload"] == name}
                check(all(len(pair) == 2 and all(label in choices for label in pair) for pair in plan["comparisons"]), "Comparison refers to an unplanned variant/mode")
        self.plans[path.stem] = plan

    def resources(self, record, operation, variant, cell, frozen, directory):
        check(record["operation"] == operation and record["variant"] == variant, "Resource operation/variant differs")
        cfg = frozen["config"]
        pool = cell["pool_bytes"] if operation in ("execute", "analyze") else GIB
        check(record["configured_pool_bytes"] == pool, "Resource configured pool differs")
        check(record["pool_policy"] == cfg["variants"][variant]["pool_policy"], "Resource pool policy differs")
        check(record["cwd"] == str(Path(cfg["variants"][variant]["checkout"]) / "python"), "Worker checkout differs")
        command = record["command"]
        check(len(command) == 10 and command[:4] == [cfg["uv"], "run", "--no-sync", "python"], "Unexpected worker command")
        check(command[5] == "--root" and command[7:9] == ["worker", operation], "Unexpected worker arguments")
        # The root recorded by the worker remains remote when this audit reads a local mirror.
        remote_root = Path(command[6])
        remote_directory = remote_root / directory.parent.name / directory.name
        check(command[4] == str(remote_root / "harness" / "harness.py") and command[9] == str(remote_directory), "Worker path differs")
        expected_group = str(Path(cfg["cgroup_parent"]) / f"{directory.name}-{operation}")
        check(record["cgroup"] == expected_group and expected_group not in self.resource_paths, "Cgroup path reused or differs")
        self.resource_paths.add(expected_group)
        check(record["temporary_directory"] == str(remote_directory / f"{operation}-tmp"), "TMPDIR is not isolated per operation")
        for moment in ("before", "after"):
            state = record[moment]
            check(int(state["memory.max"]) == cell["cgroup_bytes"] and state["memory.swap.max"] == "0", "Cgroup memory/swap limits differ")
            check(state["memory.oom.group"] == "1", "OOM group setting differs")
        check(key_values(record["before"]["cgroup.events"])["populated"] == 0, "Worker cgroup already populated")
        before, after = (key_values(record[moment]["memory.events"]) for moment in ("before", "after"))
        delta = {key: after[key] - value for key, value in before.items()}
        check(delta == record["memory_event_delta"], "OOM event delta differs")
        check(record["confirmed_oom"] == (delta["oom_kill"] > 0), "OOM classification lacks cgroup evidence")
        return record

    def actual_record(self, path, diagnostic):
        row, directory = read(path), path.parent
        identifier = directory.name
        plan, cell, frozen = self.planned[identifier]
        check(identifier in self.starts and identifier in self.ends and self.starts[identifier] <= self.ends[identifier], "Missing/invalid start and completion event")
        check(self.event_statuses[identifier] == row["status"], "Completion event differs from result")
        check(row["run_id"] == identifier and row["plan"] == plan["name"] and row["kind"] == plan["kind"], "Record identity differs from plan")
        check(diagnostic == (plan["kind"] == "diagnose") and row["executed"] is True, "Record location/executed flag differs")
        check(row["cell"] == read(directory / "cell.json") == cell, "Run cell differs from plan")
        manifest = plan["fixtures"][cell["workload"]]
        spec = manifest["metadata"]["spec"] | dict(write_mode=cell["write_mode"])
        check(read(directory / "spec.json") == spec and read(directory / "initial-snapshot.json") == manifest["metadata"], "Run spec/snapshot differs")
        check(row["contract"] == contract(cell, frozen, manifest), "Run contract differs")
        metrics_path = directory / "metrics.json"
        metrics = read(metrics_path) if metrics_path.exists() else {}
        if metrics:
            check(metrics["snapshot"] == manifest["metadata"]["version"], "Worker initial snapshot differs from fixture")
            check(metrics["operation"] == ("analyze" if diagnostic else "execute"), "Metric operation differs")
            check(metrics["configured_pool_bytes"] == cell["pool_bytes"], "Metric configured pool differs")
            check(metrics["pool_policy"] == frozen["config"]["variants"][cell["variant"]]["pool_policy"], "Metric pool description differs")
        for key, value in metrics.items():
            if key != "status":
                check(row.get(key) == value, f"Result/metrics differ: {key}")
        operation = "analyze" if diagnostic else "execute"
        execution = read(directory / f"{operation}-resources.json")
        check(row["execution"] == execution, "Result/resource record differs")
        self.resources(execution, operation, cell["variant"], cell, frozen, directory)
        consumed = producer(directory)
        check(all(row["producer"][key] == value for key, value in consumed.items()), "Producer aggregate differs from log")
        status = "confirmed_oom" if execution["confirmed_oom"] else "timeout" if execution["timeout"] else metrics.get("status", "infrastructure_error")
        if execution["exit_code"] != 0 and status not in ("confirmed_oom", "timeout"):
            status = "infrastructure_error"
        if metrics.get("identity") != frozen["identities"][cell["variant"]]["imported"]:
            status = "infrastructure_error"
        if status in ("execute_returned", "analyze_returned") and (
                consumed["yielded_rows"] != spec["source_rows"] or consumed["truncated_final_record"]):
            status = "source_consumption_error"
        check(row["status_before_validation"] == status, "Pre-validation status cannot be reproduced")
        validation_operation = "validate" if status == "execute_returned" else "validate_unchanged"
        checked = read(directory / f"{validation_operation}-resources.json")
        check(row["validation"] == checked, "Result/validation resource record differs")
        validator = frozen["config"]["validator"]
        self.resources(checked, validation_operation, validator, cell, frozen, directory)
        oracle_path = directory / f"{validation_operation}.json"
        oracle = read(oracle_path) if oracle_path.exists() else {}
        valid = (checked["exit_code"] == 0 and oracle.get("validated") is True and
                 oracle.get("validator_identity") == frozen["identities"][validator]["imported"])
        if status == "execute_returned":
            status = SUCCESS if valid else "validation_error"
        elif status == "analyze_returned":
            status = DIAGNOSTIC if valid else "failed_atomicity_check"
        elif not valid:
            status = "failed_atomicity_check"
        if "cleanup_error" in execution or "cleanup_error" in checked:
            status = "infrastructure_error"
        check(row["status"] == status, "Final status cannot be reproduced")
        unchanged = validation_operation == "validate_unchanged"
        check(row["atomicity_validated"] == (unchanged and valid), "Atomicity flag differs")
        check(valid and not checked["timeout"] and not checked["confirmed_oom"] and "cleanup_error" not in checked, "No valid independent oracle")
        check(oracle["unchanged"] == unchanged and oracle["validated_field_names"] == fields(spec), "Oracle full-field set or mode differs")
        expected_rows = max(spec["rows"], spec["source_rows"]) if spec["full"] and not unchanged else spec["rows"]
        check(oracle["rows"] == expected_rows and oracle["snapshot"] == manifest["metadata"]["version"], "Oracle row count/snapshot differs")
        counts = expected_counts(spec, unchanged)
        check(oracle["expected_counts"] == counts, "Oracle action counts differ from fixture semantics")
        if unchanged:
            check(oracle["version"] == oracle["snapshot"], "Failed/analyzed run changed latest version")
        else:
            check(metrics["merge_stats"] == counts, "API action counts differ")
            check(oracle["version"] > oracle["snapshot"] if any(counts.values()) else oracle["version"] >= oracle["snapshot"], "Successful version contract differs")
        if spec.get("small_string"):
            check(oracle["oracle"] == "all-fields-string-null", "Unexpected string oracle")
        else:
            check(oracle["oracle"] == "deterministic-v2-all-fields" and set(oracle["hashes"]) == set(fields(spec)), "Missing per-field oracle hashes")
            check(all(re.fullmatch(r"[0-9a-f]{64}", value) for value in oracle["hashes"].values()), "Invalid oracle hash")
        if status in (SUCCESS, DIAGNOSTIC):
            check(execution["exit_code"] == 0 and not execution["confirmed_oom"] and not execution["timeout"] and "cleanup_error" not in execution, "Successful run has execution resource failure")
            check(consumed["yielded_rows"] == spec["source_rows"] and not consumed["truncated_final_record"], "Successful source is incomplete")
            timer = "analyze_seconds" if diagnostic else "merge_seconds"
            check(isinstance(metrics[timer], (float, int)) and math.isfinite(metrics[timer]) and metrics[timer] > 0, "Invalid API timer")
            check(math.isclose(metrics["input_and_api_seconds"], metrics[timer] + metrics["input_materialization_seconds"], rel_tol=1e-12), "Materialized/API timer sum differs")
            if cell["input_form"] == "reader":
                check(metrics["input_materialization_seconds"] == 0, "Reader has materialization time")
        if diagnostic:
            check("merge_seconds" not in metrics, "Diagnostic leaked into execute timer")
            if status == DIAGNOSTIC:
                self.verify_hash(directory / "analyzed-plan.txt", metrics["analyzed_plan_sha256"])
        if status in RESOURCE_FAILURES:
            check(row["atomicity_validated"], "Resource failure has no unchanged proof")
        samples = [json.loads(line) for line in (directory / f"{operation}-memory.jsonl").read_text().splitlines()]
        check(row["sampled_peak_rss_bytes"] == max((item.get("VmRSS", 0) for item in samples), default=0), "Sampled RSS aggregate differs")
        check(row["cgroup_peak_bytes"] == int(execution["after"]["memory.peak"]), "Cgroup peak differs")
        for key, sample_key in (("sampled_tmp_peak_bytes", "tmp_bytes"), ("sampled_tmp_peak_allocated_bytes", "tmp_allocated_bytes"), ("sampled_tmp_peak_file_count", "tmp_files")):
            check(execution[key] == max((item[sample_key] for item in samples), default=0), f"Temporary file aggregate differs: {key}")
        for sample in samples:
            check(all(key in sample for key in ("pids", "cgroup_anon", "cgroup_file", "cgroup_shmem", "cgroup_current", "cgroup_peak")), "Missing memory attribution samples")
        original_files = {name for name in manifest["files"] if Path(name).suffix == ".lance"}
        for name, mode in (("cache-before.json", cell["cache"]), ("cache-after-execute.json", "observation_only")):
            cache = read(directory / name)
            check(cache["mode"] == mode and {item["file"] for item in cache["files"]} == original_files, "Cache operation/files differ")
            for item in cache["files"]:
                if mode == "evict_attempt":
                    check(item.get("fadvise_returned") is True or "fadvise_error" in item, "Missing eviction attempt evidence")
                for moment in ("before", "after"):
                    check(moment in item or f"{moment}_error" in item, "Missing residency observation")
                    if moment in item:
                        check(0 <= item[moment]["resident_pages"] <= item[moment]["pages"], "Invalid residency count")
        self.verified[identifier] = row

    def reference(self, path):
        row = read(path)
        identifier = path.stem
        plan, cell, frozen = self.planned[identifier]
        check(row["run_id"] == identifier and row["plan"] == plan["name"] and row["cell"] == cell, "Reference differs from plan")
        check(row["executed"] is False and row["status"] == REFERENCE and row["atomicity_validated"], "Invalid reference status")
        check("merge_seconds" not in row and "sampled_peak_rss_bytes" not in row, "Reference carries a new observation")
        check(row["contract"] == contract(cell, frozen, plan["fixtures"][cell["workload"]]), "Reference contract differs")
        prior = row["prior"]
        prior_id = prior["run_id"]
        check(prior_id in self.actual and prior == self.actual[prior_id], "Prior is not the stored actual result")
        check(prior_id in self.verified and prior["status"] in RESOURCE_FAILURES and prior["atomicity_validated"], "Prior lacks audited resource/atomicity proof")
        check(row["contract"] == prior["contract"] and self.contexts[identifier] == self.contexts[prior_id], "Reference changes the source/resource/runtime contract")
        check(plan["kind"] != "diagnose", "Diagnostic replaced by execute reference")

    def gate(self, plan):
        planned_ids = [cell["run_id"] for cell in plan["cells"]]
        observed = {**self.actual, **self.diagnostics, **self.references}
        present = [identifier for identifier in planned_ids if identifier in observed]
        check(present == planned_ids[:len(present)], "Plan has a hole before an observed cell")
        path = self.root / "gates" / f'{plan["name"]}.json'
        if not present:
            check(not path.exists(), "Empty plan has a gate record")
            return
        gate = read(path)
        check(gate["plan"] == plan["name"] and gate["planned"] == len(planned_ids) and gate["completed"] == len(present), "Gate counts differ")
        check(gate["complete"] == (len(present) == len(planned_ids)), "Gate completion differs")
        check(gate["statuses"] == [dict(run_id=identifier, status=observed[identifier]["status"], executed=observed[identifier]["executed"]) for identifier in present], "Gate statuses differ")
        cfg = self.freezes[plan["freeze"]]["config"]
        candidates = [observed[identifier] for identifier in present if cfg["variants"][observed[identifier]["cell"]["variant"]].get("role") != "baseline"]
        check(gate["candidate_passed"] == all(row["status"] in (SUCCESS, DIAGNOSTIC) for row in candidates), "Gate candidate flag differs")
        for identifier in present[:-1]:
            row = observed[identifier]
            accepted = row["status"] in (SUCCESS, DIAGNOSTIC) or (plan["kind"] == "survival" and row.get("atomicity_validated") and row["status"] in RESOURCE_FAILURES | {REFERENCE})
            check(accepted, "Plan continued after a stop-class failure")

    def prerequisite(self, identifier):
        plan, cell, frozen = self.planned[identifier]
        if plan["kind"] == "correctness":
            return
        previous = [row for key, row in self.verified.items() if key in self.actual and row["status"] == SUCCESS and
                    self.contexts[key] == self.contexts[identifier] and
                    (identifier not in self.starts or self.ends.get(key, math.inf) < self.starts[identifier])]
        for name in CORRECTNESS:
            check(any(row["kind"] == "correctness" and row["cell"]["variant"] == cell["variant"] and row["cell"]["workload"] == name and
                      row["contract"]["identity"] == content_identity(frozen["identities"][cell["variant"]]) for row in previous), f"Missing prior correctness: {name}")
        if plan["kind"] in ("pairs", "diagnose"):
            expected = contract(cell, frozen, plan["fixtures"][cell["workload"]])
            check(any(row["kind"] in ("survival", "cold") and row["contract"] == expected for row in previous), "Missing prior successful survival with the same execution context")

    def pairs(self):
        comparisons = []
        for plan in self.plans.values():
            if plan["kind"] != "pairs":
                continue
            for workload in plan["workloads"]:
                for numerator, denominator in plan["comparisons"]:
                    pairs, excluded = [], []
                    for block in (1, 2, 3):
                        group = {f'{row["cell"]["variant"]}/{row["cell"]["write_mode"]}': row for row in self.verified.values()
                                 if row["plan"] == plan["name"] and row["cell"]["workload"] == workload and row["cell"]["block"] == block and row["status"] == SUCCESS}
                        if numerator not in group or denominator not in group:
                            excluded.append(dict(block=block, unavailable=[label for label in (numerator, denominator) if label not in group]))
                            continue
                        top, bottom = group[numerator], group[denominator]
                        for field in ("pool_bytes", "cgroup_bytes", "cache", "input_form", "timeout_seconds"):
                            check(top["cell"][field] == bottom["cell"][field], f"Pair changes {field}")
                        pairs.append(dict(block=block, numerator_run=top["run_id"], denominator_run=bottom["run_id"],
                                          ratio=top["merge_seconds"] / bottom["merge_seconds"]))
                    comparisons.append(dict(plan=plan["name"], workload=workload, numerator=numerator, denominator=denominator,
                        planned_pairs=3, valid_pairs=len(pairs), pairs=pairs, excluded=excluded,
                        median_ratio=statistics.median(item["ratio"] for item in pairs) if pairs else None))
        return comparisons

    def distributions(self):
        groups = collections.defaultdict(list)
        for identifier, row in self.verified.items():
            if identifier not in self.actual or row["status"] != SUCCESS:
                continue
            cell = row["cell"]
            key = (row["plan"], row["kind"], cell["workload"], cell["variant"], cell["write_mode"],
                   cell["pool_bytes"], cell["cgroup_bytes"], cell["cache"], cell["input_form"], hash_value(self.contexts[identifier]))
            groups[key].append(row)
        output = []
        for key, rows in sorted(groups.items()):
            values = {field: summarize_numbers([row[field] for row in rows]) for field in (
                "merge_seconds", "input_and_api_seconds", "cpu_seconds", "sampled_peak_rss_bytes", "cgroup_peak_bytes",
                "ru_maxrss_before_execute_bytes", "ru_maxrss_after_execute_bytes", "new_data_file_bytes", "new_data_file_count")}
            for field in ("read_bytes", "write_bytes"):
                values[f"process_{field}"] = summarize_numbers([row["process_io_delta"][field] for row in rows])
            values["sampled_tmp_peak_bytes"] = summarize_numbers([row["execution"]["sampled_tmp_peak_bytes"] for row in rows])
            output.append(dict(zip(("plan", "kind", "workload", "variant", "write_mode", "pool_bytes", "cgroup_bytes", "cache", "input_form", "context_sha256"), key)) |
                          dict(n=len(rows), run_ids=[row["run_id"] for row in rows], metrics=values))
        return output

    def run(self):
        for path in sorted((self.root / "freezes").glob("*.json")):
            self.guarded(str(path), self.freeze, path)
        for path in sorted((self.root / "plans").glob("*.json")):
            self.guarded(str(path), self.plan, path)
        for collection, destination in (("runs", self.actual), ("diagnostics", self.diagnostics), ("references", self.references)):
            pattern = "*.json" if collection == "references" else "*/result.json"
            for path in sorted((self.root / collection).glob(pattern)):
                row = self.guarded(str(path), read, path)
                if row is not None:
                    identifier = path.stem if collection == "references" else path.parent.name
                    destination[identifier] = row
        seen = collections.Counter([*self.actual, *self.diagnostics, *self.references])
        duplicate = sorted(identifier for identifier, count in seen.items() if count > 1)
        orphan = sorted(set(seen) - set(self.planned))
        missing = sorted(set(self.planned) - set(seen))
        if duplicate or orphan:
            self.errors.append(dict(artifact="run_sets", duplicates=duplicate, orphans=orphan))
        if missing and not self.allow_incomplete:
            self.errors.append(dict(artifact="run_sets", missing=missing))
        for collection in ("runs", "diagnostics"):
            incomplete = [path.name for path in (self.root / collection).glob("*") if path.is_dir() and not (path / "result.json").exists()]
            if incomplete:
                self.warnings.append(dict(unfinished_directories=incomplete, collection=collection))
                if set(incomplete) - set(self.planned):
                    self.errors.append(dict(artifact=collection, orphan_directories=sorted(set(incomplete) - set(self.planned))))
        events = self.root / "events.jsonl"
        if events.exists():
            for line in events.read_text().splitlines():
                event = self.guarded("events.jsonl", json.loads, line)
                if event is not None:
                    destination = self.starts if event["status"] == "started" else self.ends
                    if event["run_id"] in destination:
                        self.errors.append(dict(artifact="events.jsonl", error=f'Duplicate event: {event["run_id"]}/{event["status"]}'))
                    destination[event["run_id"]] = event["wall_ns"]
                    if event["status"] != "started":
                        self.event_statuses[event["run_id"]] = event["status"]
        for identifier in self.actual:
            self.guarded(identifier, self.actual_record, self.root / "runs" / identifier / "result.json", False)
        for identifier in self.diagnostics:
            self.guarded(identifier, self.actual_record, self.root / "diagnostics" / identifier / "result.json", True)
        for identifier in self.references:
            self.guarded(identifier, self.reference, self.root / "references" / f"{identifier}.json")
        for plan in self.plans.values():
            self.guarded(f'gate:{plan["name"]}', self.gate, plan)
        for identifier in set(seen) & set(self.planned):
            self.guarded(f"prerequisite:{identifier}", self.prerequisite, identifier)
        ratios = self.guarded("paired_comparisons", self.pairs) or []
        distributions = self.guarded("distributions", self.distributions) or []
        summary_path = self.root / "summary.json"
        if summary_path.exists():
            self.guarded("summary.json", self.summary, read(summary_path), ratios)
        counts = dict(planned=len(self.planned), actual_executions=len(self.actual), diagnostics=len(self.diagnostics),
                      references=len(self.references), missing=len(missing), audited_actual=sum(key in self.verified for key in self.actual),
                      audited_diagnostics=sum(key in self.verified for key in self.diagnostics))
        return dict(audit_status="failed" if self.errors else "incomplete" if missing or not seen else "passed",
            root=str(self.root), counts=counts, planned_ids=sorted(self.planned), actual_ids=sorted(self.actual),
            diagnostic_ids=sorted(self.diagnostics), reference_ids=sorted(self.references), missing_ids=missing,
            execution_status_counts=dict(collections.Counter(row["status"] for row in self.actual.values())),
            failure_runs=[dict(run_id=key, status=row["status"], atomicity_validated=row.get("atomicity_validated"))
                          for key, row in self.actual.items() if row["status"] != SUCCESS],
            references=[dict(run_id=key, prior_run_id=row["prior"]["run_id"]) for key, row in self.references.items()],
            frozen_identities={name: {label: dict(extension_sha256=identity["imported"]["extension_sha256"],
                source_hashes_sha256=hash_value(identity["tree"]["source_hashes"]), head=identity["tree"]["head"],
                pool_policy=identity["pool_policy"]["source_review"],
                context_sha256=hash_value(execution_context(frozen, label)))
                for label, identity in frozen["identities"].items()} for name, frozen in self.freezes.items()},
            paired_comparisons=ratios, distributions=distributions, errors=self.errors, warnings=self.warnings,
            audit_script_sha256=sha256(Path(__file__)), live_file_verification_requested=self.verify_files,
            planned_live_files_verified=self.verify_files and not self.errors,
            limits=["Recorded oracle assertions are audited; dataset values are not reread by this script.",
                    "Per-field digests follow scan order and are not compared across candidates.",
                    "Source/binary/fixture hashes are cross-checked as recorded; live files require --verify-files.",
                    "A coherent resource failure is evidence, not a successful candidate or a timing sample.",
                    "RSS is sampled maximum single-process RSS; cgroup includes charged cache and is not total RSS.",
                    "TMPDIR footprint is sampled, not cumulative spill writes. fadvise is advisory."])

    def summary(self, summary, ratios):
        check(summary["actual_executions"] == len(self.actual), "Summary actual execution count differs")
        check(summary["statuses"] == dict(collections.Counter(row["status"] for row in self.actual.values())), "Summary statuses differ")
        check({row["run_id"] for row in summary["results"]} == set(self.actual), "Summary execution set differs")
        check({row["run_id"] for row in summary["diagnostics"]} == set(self.diagnostics), "Summary diagnostic set differs")
        check({row["run_id"] for row in summary["references"]} == set(self.references), "Summary reference set differs")
        expected_keys = ("run_id", "plan", "kind", "cell", "status", "merge_seconds", "cpu_seconds", "new_data_file_bytes",
                         "new_data_file_count", "sampled_peak_rss_bytes", "cgroup_peak_bytes", "process_io_delta", "atomicity_validated", "producer")
        for row in summary["results"]:
            actual = self.actual[row["run_id"]]
            check(row == {key: actual.get(key) for key in expected_keys}, "Summary result values differ from original result")
        check(all(row == self.references[row["run_id"]] for row in summary["references"]), "Summary reference differs")
        check(all(row == self.diagnostics[row["run_id"]] for row in summary["diagnostics"]), "Summary diagnostic differs")
        expected = {(row["plan"], row["workload"], row["numerator"], row["denominator"]): row for row in ratios}
        check(len(summary["paired_comparisons"]) == len(expected), "Summary comparison count differs")
        for row in summary["paired_comparisons"]:
            actual = expected[(row["plan"], row["workload"], row["numerator"], row["denominator"])]
            check(row["valid_pairs"] == actual["valid_pairs"] and row["planned_pairs"] == 3, "Summary pair count differs")
            check(row["ratios"] == [dict(block=item["block"], ratio=item["ratio"]) for item in actual["pairs"]], "Summary same-block ratios differ")
            check(row["median_ratio"] == actual["median_ratio"], "Summary ratio median differs")


def print_tables(report):
    counts = report["counts"]
    print(f'Audit: {report["audit_status"]}; planned={counts["planned"]}, execute={counts["actual_executions"]}, '
          f'diagnostic={counts["diagnostics"]}, references={counts["references"]}, missing={counts["missing"]}')
    selected = [row for row in report["distributions"] if row["kind"] == "pairs"]
    if not selected:
        selected = [row for row in report["distributions"] if row["kind"] in ("survival", "cold")]
    if selected:
        print("\n| Plan/workload | Variant/mode | Pool MiB | Cache/input | n | API median s | RSS MiB | Cgroup MiB | New .lance bytes |")
        print("|---|---|---:|---|---:|---:|---:|---:|---:|")
        for row in selected:
            metric = row["metrics"]
            print(f'| {row["plan"]}/{row["workload"]} | {row["variant"]}/{row["write_mode"]} | {row["pool_bytes"] / (1 << 20):g} | '
                  f'{row["cache"]}/{row["input_form"]} | {row["n"]} | {metric["merge_seconds"]["median"]:.6f} | '
                  f'{metric["sampled_peak_rss_bytes"]["median"] / (1 << 20):.2f} | {metric["cgroup_peak_bytes"]["median"] / (1 << 20):.2f} | '
                  f'{metric["new_data_file_bytes"]["median"]:g} |')
    if report["paired_comparisons"]:
        print("\n| Plan/workload | Numerator / denominator | Valid pairs | Median same-block ratio |")
        print("|---|---|---:|---:|")
        for row in report["paired_comparisons"]:
            ratio = "unavailable" if row["median_ratio"] is None else f'{row["median_ratio"]:.6f}'
            print(f'| {row["plan"]}/{row["workload"]} | {row["numerator"]} / {row["denominator"]} | {row["valid_pairs"]}/3 | {ratio} |')
    for item in report["errors"]:
        print(f'ERROR {json.dumps(item, ensure_ascii=False)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, help="Optional derived JSON report; measurement artifacts are never modified")
    parser.add_argument("--verify-files", action="store_true", help="Verify actual source, extension, build-log and fixture bytes on this host")
    parser.add_argument("--allow-incomplete", action="store_true", help="Permit an unfinished suffix; report remains incomplete, never passed")
    args = parser.parse_args()
    report = Audit(args.root.resolve(), args.verify_files, args.allow_incomplete).run()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print_tables(report)
    return 1 if report["errors"] else 2 if report["audit_status"] == "incomplete" else 0


if __name__ == "__main__":
    sys.exit(main())
