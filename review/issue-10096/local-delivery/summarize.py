"""Summarize raw query samples from the issue #10096 workload."""

import json
import math
import statistics
import sys
from pathlib import Path


def describe(values):
    values = sorted(values)
    if not values:
        return None
    return {
        "n": len(values),
        "median": statistics.median(values),
        "p95_nearest_rank": values[math.ceil(len(values) * 0.95) - 1],
        "min": values[0],
        "max": values[-1],
    }


root = Path(sys.argv[1])
groups = {}
rounds = {}
for path in sorted(root.glob("*-session-*.jsonl")):
    round_id = path.name.split("-", 1)[0]
    for line in path.read_text().splitlines():
        sample = json.loads(line)
        if sample["warmup"]:
            continue
        key = (sample["cache"], sample["label"])
        groups.setdefault(key, []).append(sample)
        rounds.setdefault((*key, round_id), []).append(sample["latency_us"])

summary = {}
for (cache, label), samples in sorted(groups.items()):
    summary.setdefault(cache, {})[label] = {
        "latency_us": describe([s["latency_us"] for s in samples]),
        "store_read_bytes": describe([s["store_read_bytes"] for s in samples]),
        "plan_bytes_read": describe([s["plan_bytes_read"] for s in samples]),
        "rows_scanned": describe([
            s["all_counts"]["rows_scanned"] for s in samples
            if "rows_scanned" in s["all_counts"]
        ]),
    }
for cache in summary:
    ratios = {}
    for round_id in sorted({key[2] for key in rounds if key[0] == cache}):
        baseline = statistics.median(rounds[(cache, "baseline", round_id)])
        fixed = statistics.median(rounds[(cache, "fixed", round_id)])
        ratios[round_id] = baseline / fixed
    summary[cache]["baseline_over_fixed_round_medians"] = ratios

print(json.dumps(summary, indent=2))
