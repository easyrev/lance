"""Aggregate execute results without treating diagnostic plans as successful runs."""

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

root = Path(sys.argv[1])
rows = []
for variant in ("main", "fix", "pr10077", "statistics"):
    for path in sorted((root / variant).glob("*.json")):
        if path.name.endswith(".rss.json"):
            continue
        result = json.loads(path.read_text())
        if result.get("operation") != "execute":
            continue
        run = path.stem
        if "causal" in run:
            continue
        journal = path.with_suffix(".journal")
        journal_text = journal.read_text() if journal.exists() else ""
        status = result.get("status", "missing")
        if "oom-kill" in journal_text:
            status = "oom"
        elif status == "ok" and not result.get("validated"):
            status = "unvalidated"
        elif status in ("running", "started"):
            status = "incomplete"
        samples_path = path.with_suffix(".rss.jsonl")
        samples = (
            [json.loads(line) for line in samples_path.read_text().splitlines()]
            if samples_path.exists()
            else []
        )
        sampled_rss = max([0] + [sample[1] for sample in samples])
        sampled_anon = max([0] + [sample[2] for sample in samples if len(sample) > 2])
        sampled_cgroup = max([0] + [sample[6] for sample in samples if len(sample) > 6])
        row = {
            "variant": variant,
            "run": run,
            "status": status,
            "seconds": result.get("seconds"),
            "source_prepare_seconds": result.get("source_prepare_seconds"),
            "prepare_and_merge_seconds": result.get("source_prepare_and_merge_seconds"),
            "rss_gib": max(result.get("process_peak_rss_bytes", 0), sampled_rss)
            / 2**30,
            "anon_gib": max(result.get("sampled_peak_anon_bytes", 0), sampled_anon)
            / 2**30,
            "cgroup_gib": max(result.get("cgroup_memory_peak_bytes", 0), sampled_cgroup)
            / 2**30,
            "average_cpu_cores": result.get("average_cpu_cores"),
            "target_mrows_per_second": result.get("target_rows_per_second", 0) / 1e6,
            "source_mrows_per_second": result.get("source_rows_per_second", 0) / 1e6,
            "updated_rows": result.get("merge_stats", {}).get("num_updated_rows"),
            "error": result.get("error", ""),
        }
        rows.append(row)

if not rows:
    raise SystemExit("No execute results yet")
with (root / "runs.csv").open("w") as out:
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

groups = defaultdict(list)
for row in rows:
    case = (
        row["run"].rsplit("-", 1)[0]
        if row["run"].endswith(("-1", "-2"))
        else row["run"]
    )
    groups[row["variant"], case].append(row)

summary = []
for (variant, case), group in groups.items():
    successful = [row for row in group if row["status"] == "ok"]
    item = {
        "variant": variant,
        "case": case,
        "runs": len(group),
        "completed": len(successful),
        "statuses": ",".join(row["status"] for row in group),
    }
    for metric in (
        "seconds",
        "source_prepare_seconds",
        "prepare_and_merge_seconds",
        "rss_gib",
        "anon_gib",
        "cgroup_gib",
        "average_cpu_cores",
        "target_mrows_per_second",
        "source_mrows_per_second",
    ):
        item["median_" + metric] = (
            statistics.median(row[metric] for row in successful) if successful else None
        )
    item["observed_rss_gib_all_runs"] = max(row["rss_gib"] for row in group)
    summary.append(item)
with (root / "summary.csv").open("w") as out:
    writer = csv.DictWriter(out, fieldnames=list(summary[0]))
    writer.writeheader()
    writer.writerows(summary)
print(json.dumps(summary, indent=2))
