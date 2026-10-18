"""Summarize all terminal states and same-block successful pairs."""
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent


def main():
    metrics = []
    for path in sorted((ROOT / "runs").glob("*/metrics.json")):
        row = json.loads(path.read_text())
        row["run_id"] = path.parent.name
        metrics.append(row)
    manifest = ROOT / "run-manifest.jsonl"
    latest = {}
    if manifest.exists():
        for line in manifest.read_text().splitlines():
            row = json.loads(line)
            latest[row["run_id"]] = row
    existing = {row["run_id"] for row in metrics}
    metrics += [row for run_id, row in latest.items() if run_id not in existing]
    fields = ["run_id", "variant", "workload", "source", "block", "formal", "status", "validated", "merge_seconds", "input_materialization_seconds", "cpu_seconds", "average_cpu_cores", "sampled_peak_rss_bytes", "sampled_peak_anon_bytes", "cgroup_peak_bytes", "effective_p", "source_prepare_seconds", "pool_observed_peak_bytes", "scan_take_bytes", "updated", "inserted", "deleted"]
    with (ROOT / "summary.csv").open("w") as output:
        writer = csv.DictWriter(output, fields)
        writer.writeheader()
        for metric in metrics:
            row = {field: metric.get(field) for field in fields}
            row.update(workload=metric.get("spec", {}).get("name"), source=metric.get("spec", {}).get("source"))
            row["cgroup_peak_bytes"] = metric.get("execution", {}).get("after", {}).get("memory.peak")
            row["effective_p"] = metric.get("resources", {}).get("effective_p")
            row["source_prepare_seconds"] = metric.get("source_prepared", {}).get("seconds")
            completion = metric.get("execute_complete", {})
            row["pool_observed_peak_bytes"] = completion.get("reservation_observed_peak_bytes")
            row["scan_take_bytes"] = completion.get("scan_take_bytes")
            for action in ("updated", "inserted", "deleted"):
                row[action] = metric.get("merge_stats", {}).get(f"num_{action}_rows")
            writer.writerow(row)
    pairs = []
    rng = np.random.default_rng(9505)
    for workload, source, candidate, control in [
        ("F16", "reader", "Ccore", "Cbudget"),
        ("F16", "reader", "Cbudget", "Cprep"),
        ("F16", "reader", "Ccore", "B"),
        ("F16", "reader", "Ccore", "P_reconstructed"),
        ("F16", "materialized", "Ccore", "B"),
        ("R", "reader", "Ccore", "B"),
        ("Wn", "reader", "Clate", "Ccore"),
        ("Wn", "reader", "Cbudget_late", "Cbudget"),
    ]:
        selected = [m for m in metrics if m.get("formal") and m.get("spec", {}).get("name") == workload and m["spec"]["source"] == source and m.get("variant") in (candidate, control)]
        blocks = sorted({m["block"] for m in selected})
        ratios = []
        raw = []
        for block in blocks:
            choices = {m["variant"]: m for m in selected if m["block"] == block}
            a, b = choices.get(candidate), choices.get(control)
            success = a and b and a["status"] == b["status"] == "validated_success"
            raw.append(dict(block=block, candidate_seconds=a.get("merge_seconds") if a else None, control_seconds=b.get("merge_seconds") if b else None, candidate_status=a.get("status") if a else "not_run", control_status=b.get("status") if b else "not_run"))
            if success:
                ratios.append(a["merge_seconds"] / b["merge_seconds"])
        if ratios:
            bootstrap = np.median(rng.choice(ratios, size=(10000, len(ratios))), axis=1)
            pairs.append(dict(workload=workload, source=source, candidate=candidate, control=control, attempted_blocks=len(blocks), valid_pairs=len(ratios), ratios=ratios, median_ratio=float(np.median(ratios)), ratio_range=[min(ratios), max(ratios)], bootstrap_95_percent_conditional=np.quantile(bootstrap, [.025, .975]).tolist(), raw=raw))
    (ROOT / "paired-results.json").write_text(json.dumps(pairs, indent=2) + "\n")
    states = Counter(m.get("status", "missing") for m in metrics)
    (ROOT / "status-counts.json").write_text(json.dumps(dict(total=len(metrics), terminal_states=dict(states)), indent=2) + "\n")
    print(json.dumps(dict(total=len(metrics), states=dict(states), pairs=[{k:p[k] for k in ("workload", "source", "candidate", "control", "valid_pairs", "median_ratio")} for p in pairs]), indent=2))


if __name__ == "__main__":
    main()
