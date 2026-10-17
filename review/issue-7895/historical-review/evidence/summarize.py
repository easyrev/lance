"""Reduce raw benchmark observations without dropping runs or outliers."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics

parser = argparse.ArgumentParser()
parser.add_argument("fixture", type=Path)
parser.add_argument("--repetitions", type=int, default=5)
args = parser.parse_args()
groups = defaultdict(list)
fixture = json.loads((args.fixture / "fixture.json").read_text())
label_hashes = defaultdict(set)
label_source_hashes = defaultdict(set)
environments = set()
for path in sorted(args.fixture.glob("*/result.json")):
    result = json.loads(path.read_text())
    if result["label"] not in ("baseline", "candidate"):
        continue
    assert result["fixture"] == fixture, path
    assert result["error"] is None and result["correct"], path
    assert result["retries"] == 3, path
    assert result["commit_versions"] == ([2, 3] if result["conflict"] else [2]), path
    assert result["stats"] == {"num_inserted_rows": fixture["rows"] - 1,
                               "num_updated_rows": 1, "num_deleted_rows": 0}, path
    label_hashes[result["label"]].add(result["extension_sha256"])
    label_source_hashes[result["label"]].add(tuple(sorted(result["source_sha256"].items())))
    environments.add((result["python"], result["pyarrow"], result["cache"],
                      result["probe_sha256"], tuple(sorted(result["thread_limits"].items())),
                      result["arrow_cpu_count"], result["arrow_io_thread_count"]))
    groups[(result["label"], result["kind"], result["conflict"])].append(result)

expected_groups = {(label, kind, conflict) for label in ("baseline", "candidate")
                   for kind in ("lance", "arrow", "scanner") for conflict in (False, True)}
assert set(groups) == expected_groups, (set(groups), expected_groups)
assert all(len(hashes) == 1 for hashes in label_hashes.values()), label_hashes
assert all(len(hashes) == 1 for hashes in label_source_hashes.values()), label_source_hashes
assert len(environments) == 1, environments
expected_trials = {str(trial) for trial in range(1, args.repetitions + 1)}

summary = []
for (label, kind, conflict), runs in sorted(groups.items()):
    assert {run["trial"] for run in runs} == expected_trials, (label, kind, conflict)
    assert len(runs) == args.repetitions, (label, kind, conflict)
    entry = {"label": label, "kind": kind, "conflict": conflict,
             "count": len(runs), "trials": [run["trial"] for run in runs],
             "extension_sha256": next(iter(label_hashes[label])),
             "source_sha256": dict(next(iter(label_source_hashes[label])))}
    for key in ("elapsed_s", "first_commit_elapsed_s", "first_commit_cpu_s",
                "cpu_s", "concurrent_update_elapsed_s", "max_rss_kib", "user_s", "system_s",
                "replay_directory_count", "spill_file_count", "spill_file_unlink_bytes"):
        values = [run[key] for run in runs]
        entry[key] = {"median": statistics.median(values), "min": min(values),
                      "max": max(values), "values": values}
    for key in ("rchar", "wchar", "read_bytes", "write_bytes", "cancelled_write_bytes"):
        values = [run["io_delta"][key] for run in runs]
        entry["io_" + key] = {"median": statistics.median(values), "values": values}
    assert all(run["correct"] for run in runs)
    summary.append(entry)
print(json.dumps(summary, indent=2))
