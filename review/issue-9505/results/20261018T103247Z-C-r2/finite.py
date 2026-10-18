"""Finite, sequential benchmark stages. No compilation is performed here."""
import argparse
import hashlib
import json
import random
from pathlib import Path

import bench


def measured(variant, spec, name, block=0, formal=False, limit=8 * bench.GIB, pool=bench.GIB):
    manifest = bench.ROOT / "run-manifest.jsonl"
    for previous in [json.loads(line) for line in manifest.read_text().splitlines()] if manifest.exists() else []:
        if (previous.get("status") in ("confirmed_oom", "resource_exhausted")
                and previous.get("variant") == variant and previous.get("spec") == spec
                and previous.get("pool_bytes") == pool and previous.get("memory_max_bytes") == limit):
            bench.append(manifest, dict(run_id=name, variant=variant, spec=spec, block=block, formal=formal,
                                       status="not_repeated_after_" + previous["status"], previous_run_id=previous["run_id"],
                                       pool_bytes=pool, memory_max_bytes=limit))
            print(f"{name}: not repeated after {previous['run_id']}", flush=True)
            return previous["status"]
    status = bench.run(variant, spec, name, block=block, formal=formal, limit=limit, pool=pool)
    if status in ("validation_error", "infrastructure_error", "source_error", "execution_error", "timeout/cancelled"):
        raise RuntimeError(f"Hard gate failed: {name}: {status}")
    return status


def main(stage):
    if not (bench.ROOT / "freeze.json").exists():
        raise RuntimeError("Reviewed source and extension must be frozen first")
    frozen = json.loads((bench.ROOT / "freeze.json").read_text())
    for name, expected in frozen["source_hashes"].items():
        with open(Path("/mnt/lance/checkouts/C") / name, "rb") as source:
            assert hashlib.file_digest(source, "sha256").hexdigest() == expected, name
    for name, expected in frozen["harness_hashes"].items():
        with open(bench.ROOT / name, "rb") as source:
            assert hashlib.file_digest(source, "sha256").hexdigest() == expected, name
    identity = frozen["identities"]["C"]
    with open(identity["extension"], "rb") as extension:
        assert hashlib.file_digest(extension, "sha256").hexdigest() == identity["extension_sha256"]
    if stage == "gate2":
        plan = json.loads((bench.ROOT / "planned-matrix.json").read_text())
        for entry in plan["runs"]:
            if entry["gate"] != 2:
                continue
            spec = bench.workload(entry["workload"])
            name = f'g2-{spec["name"]}-{entry["variant"]}'
            status = measured(entry["variant"], spec, name, limit=entry["memory_max_bytes"])
            if entry["variant"] == "Ccore" and spec["name"] in ("F4", "R") and status != "validated_success":
                raise RuntimeError(f"Core completion gate failed: {name}: {status}")
    elif stage.startswith("core"):
        blocks = range(1, 4) if stage == "core3" else range(4, 6)
        plan = json.loads((bench.ROOT / "planned-matrix.json").read_text())
        for entry in plan["runs"]:
            if entry["gate"] != 3 or entry["block"] not in blocks:
                continue
            spec = bench.workload(entry["workload"])
            source = entry.get("source", "reader")
            spec["source"] = source
            name = f'g3-{spec["name"]}-{source}-b{entry["block"]}-{entry["variant"]}'
            pause_path = bench.ROOT / "paused-branches.json"
            paused = json.loads(pause_path.read_text()) if pause_path.exists() else {}
            reason = paused.get(f'{spec["name"]}:{source}')
            if reason:
                bench.append(bench.ROOT / "run-manifest.jsonl", dict(run_id=name, block=entry["block"], variant=entry["variant"],
                             workload=spec["name"], spec=spec, formal=True, status="paused_regression", reason=reason,
                             pool_bytes=entry["pool_bytes"], memory_max_bytes=entry["memory_max_bytes"]))
                continue
            status = measured(entry["variant"], spec, name, entry["block"], True, entry["memory_max_bytes"])
            if entry["variant"] == "Ccore" and status != "validated_success":
                raise RuntimeError(f"Core completion gate failed: {name}: {status}")
    elif stage == "boundaries":
        for count in (100_000, 1_000_000):
            for variant in ("B", "Ccore"):
                spec = bench.workload("F4") | dict(source_rows=count)
                measured(variant, spec, f"g3-F4-source{count}-{variant}")
    elif stage == "skew":
        spec = json.loads((bench.ROOT / "skew-workload.json").read_text())
        for variant in ("B", "Cbudget", "Ccore"):
            measured(variant, spec, f"g3-skew-{variant}")
    elif stage == "late-smoke":
        for name in ("V_sparse", "Wn", "W_dense"):
            for variant in ("Ccore", "Clate"):
                measured(variant, bench.workload(name), f"g4-smoke-{name}-{variant}")
    elif stage in ("late5", "budget-late5"):
        pair = ("Ccore", "Clate") if stage == "late5" else ("Cbudget", "Cbudget_late")
        order = random.Random(9505)
        for block in range(1, 6):
            variants = list(pair)
            order.shuffle(variants)
            for variant in variants:
                measured(variant, bench.workload("Wn"), f"g4-{stage}-Wn-b{block}-{variant}", block, True)
        if stage == "budget-late5":
            for variant in pair:
                measured(variant, bench.workload("W_dense"), f"g4-budget-dense-{variant}")
    elif stage == "low":
        status = measured("Ccore", bench.workload("F4"), "g4-low-F4-Ccore", limit=2 * bench.GIB, pool=256 * bench.MIB)
        if status != "validated_success":
            raise RuntimeError("Fixed low-memory success gate failed")
        for name in ("Wn", "Ws"):
            for variant in ("Ccore", "Clate"):
                measured(variant, bench.workload(name), f"g4-low-{name}-{variant}", limit=2 * bench.GIB)
    elif stage == "slow":
        schedules = dict(first=dict(batch_rows=1, delays={"0": 0.25}),
                         later=dict(batch_rows=1, delays={"2": 0.25}),
                         pending=dict(batch_rows=1, pending_after=2),
                         batch_boundary=dict(batch_rows=1, zero_batches=1024))
        for schedule, changes in schedules.items():
            for variant in ("U", "B", "P_reconstructed", "Ccore"):
                spec = bench.workload("tiny") | changes | dict(strace=True)
                run_id = f"g1-slow-{schedule}-{variant}"
                status = bench.run(variant, spec, run_id, timeout=3 if schedule == "pending" else 30)
                if schedule == "pending":
                    assert status == "timeout/cancelled", status
                    validation = bench.isolated("validate_cancel", "U", spec, bench.ROOT / "runs" / run_id, 2 * bench.GIB, bench.GIB)
                    assert validation["exit_code"] == 0, validation
    else:
        raise ValueError(stage)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage")
    main(parser.parse_args().stage)
