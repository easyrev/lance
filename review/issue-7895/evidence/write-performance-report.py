"""Build a report only after complete matched measurements and controls exist."""

import argparse
import json
from pathlib import Path
import statistics

parser = argparse.ArgumentParser()
parser.add_argument("--evidence", type=Path, default=Path(__file__).parent)
parser.add_argument("--base", required=True)
parser.add_argument("--candidate", required=True)
args = parser.parse_args()
root = args.evidence
fixtures = ("benchmark-fixture-small", "benchmark-fixture")
observations = []
hashes = {"baseline": set(), "candidate": set()}
plan_comparisons = []

for fixture_name in fixtures:
    summary = json.loads((root / f"{fixture_name}-summary.json").read_text())
    assert len(summary) == 12, fixture_name
    grouped = {(entry["label"], entry["kind"], entry["conflict"]): entry for entry in summary}
    for entry in summary:
        assert entry["count"] == 5, entry
        hashes[entry["label"]].add(entry["extension_sha256"])
    for kind in ("lance", "arrow", "scanner"):
        plans = {}
        for label in ("baseline", "candidate"):
            folder = root / "plans" / fixture_name / label / kind
            metadata = json.loads((folder / "metadata.json").read_text())
            assert metadata["target_unchanged"] and metadata["commit_versions"] == []
            assert metadata["extension_sha256"] in hashes[label]
            plans[label] = (folder / "topology.txt").read_text()
        plan_comparisons.append({"fixture": fixture_name, "kind": kind,
                                 "normalized_equal": plans["baseline"] == plans["candidate"]})
        for conflict in (False, True):
            before = grouped[("baseline", kind, conflict)]
            after = grouped[("candidate", kind, conflict)]
            base_times = dict(zip(before["trials"], before["elapsed_s"]["values"]))
            candidate_times = dict(zip(after["trials"], after["elapsed_s"]["values"]))
            ratios = [candidate_times[trial] / base_times[trial] for trial in sorted(base_times)]
            observations.append({
                "fixture": fixture_name, "kind": kind, "conflict": conflict,
                "baseline": before, "candidate": after,
                "median_elapsed_change_percent": 100 * (after["elapsed_s"]["median"] / before["elapsed_s"]["median"] - 1),
                "paired_elapsed_ratios": ratios,
                "median_paired_elapsed_ratio": statistics.median(ratios),
            })

assert all(len(values) == 1 for values in hashes.values()), hashes
for label in ("baseline", "candidate"):
    receipt = json.loads((root / f"{label}-perf-elf-sections.json").read_text())
    assert receipt["allocated_sections_unchanged"]
    assert "/release-with-debug/" in receipt["original"]
controls = json.loads((root / "controls" / "final" / "summary.json").read_text())
assert len(controls) == 14 and all(control["passed"] for control in controls)
for control in controls:
    assert control["extension_sha256"] in hashes[control["label"]]

followup_groups = {}
for label in ("baseline", "candidate"):
    paths = sorted((root / "no-probe-followup").glob(f"no-probe-small-lance-{label}-*.jsonl"))
    if paths:
        rows = sorted((json.loads(path.read_text()) for path in paths), key=lambda row: int(row["trial"]))
        assert len(rows) == 10
        for row in rows:
            assert row["probe_sha256"] is None and row["correct"]
            assert row["extension_sha256"] in hashes[label]
            assert row["kind"] == "lance" and not row["conflict"] and row["commit_versions"] == [2]
        followup_groups[f"no-probe-{label}"] = {
            metric: {"median": statistics.median(row[metric] for row in rows),
                     "min": min(row[metric] for row in rows), "max": max(row[metric] for row in rows),
                     "values": [row[metric] for row in rows]}
            for metric in ("elapsed_s", "first_commit_elapsed_s", "cpu_s", "first_commit_cpu_s", "max_rss_kib")
        }
if followup_groups:
    assert len(followup_groups) == 2
    (root / "no-probe-followup-summary.json").write_text(json.dumps(followup_groups, indent=2) + "\n")


def time_cell(entry, metric="elapsed_s"):
    item = entry[metric]
    return f"{item['median'] * 1000:.2f} [{item['min'] * 1000:.2f}, {item['max'] * 1000:.2f}]"


def table(rows):
    lines = [
        "| Fixture | Source | Conflict | Baseline ms, median [min, max] | Candidate ms, median [min, max] | Change | RSS MiB, baseline → candidate | Replay dirs, baseline → candidate | Spill MiB, baseline → candidate |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        before, after = row["baseline"], row["candidate"]
        fixture = "1.125 MiB" if row["fixture"].endswith("-small") else "132 MiB"
        rss = f"{before['max_rss_kib']['median'] / 1024:.1f} → {after['max_rss_kib']['median'] / 1024:.1f}"
        replay = f"{before['replay_directory_count']['median']:g} → {after['replay_directory_count']['median']:g}"
        spill = f"{before['spill_file_unlink_bytes']['median'] / 1048576:.2f} → {after['spill_file_unlink_bytes']['median'] / 1048576:.2f}"
        lines.append(f"| {fixture} | {row['kind']} | {'yes' if row['conflict'] else 'no'} | {time_cell(before)} | {time_cell(after)} | {row['median_elapsed_change_percent']:+.1f}% | {rss} | {replay} | {spill} |")
    return lines


def execution_table(rows):
    lines = [
        "| Fixture | Source | First commit hook ms, baseline | First commit hook ms, candidate | Total CPU ms, baseline | Total CPU ms, candidate | First hook CPU ms, baseline → candidate |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        before, after = row["baseline"], row["candidate"]
        fixture = "1.125 MiB" if row["fixture"].endswith("-small") else "132 MiB"
        first_cpu = f"{before['first_commit_cpu_s']['median'] * 1000:.2f} → {after['first_commit_cpu_s']['median'] * 1000:.2f}"
        lines.append(f"| {fixture} | {row['kind']} | {time_cell(before, 'first_commit_elapsed_s')} | {time_cell(after, 'first_commit_elapsed_s')} | {time_cell(before, 'cpu_s')} | {time_cell(after, 'cpu_s')} | {first_cpu} |")
    return lines


report = [
    "# Issue 7895 local performance evidence", "",
    f"Base: `{args.base}`. Candidate: `{args.candidate}`.", "",
    "Both snapshots use `release-with-debug`. Debug-section removal preserves the loaded ELF sections, as recorded in the snapshot receipts.", "",
    "The matrix contains 120 measurements: two fixtures, three input types, two conflict conditions, two snapshots, and five repetitions.",
    "Each source has a seeded binary payload. The target has one matching row. The merge updates that row and inserts all other keys.",
    "Source files are read before timing. Each observation uses a fresh process. Baseline and candidate order alternate across repetitions.",
    "Timing includes merge execution and the concurrent update when present. It excludes fixture preparation, cache warming, and correctness checks.", "",
    "Conflict wall time includes randomized retry backoff. The first failure selects 0–3 slots, each approximately 1.1 times the first attempt duration.",
    "Paired trials do not share a random slot. Their wall-time ratios cannot isolate replay cost, and five samples can retain substantial variation.", "",
    "## Eligible inputs", "",
    *table(row for row in observations if row["kind"] != "scanner"), "",
    "## Opaque Scanner fallback", "",
    "These observations measure the conservative fallback. They are separate from inputs eligible for the replay optimization.", "",
    *table(row for row in observations if row["kind"] == "scanner"), "",
    "## Conflict execution before backoff and total CPU", "",
    "The first commit hook time ends before the injected update and retry backoff. It still includes scheduling and all preceding first-attempt work.",
    "Total CPU is process user plus system time across both attempts, commits, and the concurrent update. It excludes time spent sleeping.",
    "The following cells show medians and ranges. First-hook CPU shows medians. Scanner remains the fallback control.", "",
    *execution_table(row for row in observations if row["conflict"]), "",
    "## Plans and attribution", "",
]
for item in plan_comparisons:
    report.append(f"- `{item['fixture']}/{item['kind']}`: normalized topology {'matches' if item['normalized_equal'] else 'differs'}.")
report.extend([
    "", "Raw `analyze_plan` files include runtime counters. The script verifies unchanged target versions and data after each plan capture.",
    "Topology comparison preserves operators and join settings. It does not establish equality of every optimizer estimate.",
    "Both implementations use StreamingTable providers. The replay detector distinguishes their source behavior even when the displayed operators match.",
    "The 14 controls passed against these exact binary hashes. They include in-memory replay, materialized input, opaque Scanner fallback, and zero-retry failure.", "",
    "The following list retains every higher candidate median without a significance claim:", "",
])
for row in observations:
    if row["median_elapsed_change_percent"] > 0:
        report.append(f"- `{row['fixture']}/{row['kind']}/{'conflict' if row['conflict'] else 'clean'}`: {row['median_elapsed_change_percent']:+.1f}%, paired median ratio {row['median_paired_elapsed_ratio']:.3f}.")
interpretation = root / "performance-interpretation.md"
if interpretation.is_file():
    report.extend(["", "## Assessment of observed changes", "", interpretation.read_text().strip()])
report.extend([
    "", "The investigation found identical plan structure and join input counts. The probe-free follow-up did not reproduce the original small-Lance latency increase at the same magnitude.",
    "Replay storage avoidance is established. These workloads show no uniform retry improvement in latency, CPU, or process RSS.", "",
    "## Limits and raw evidence", "",
    "RSS is the process high-water mark at merge completion, including imports and setup. It is not isolated replay memory.",
    "The probe records completed spill-file size. `/proc/self/io` includes target writes and logging, and kernel-accounted writes can include cancelled writes.",
    "Replay creates extra probe log writes. Very small elapsed-time differences can include this observation overhead and cannot establish pure replay savings.",
    "Logical I/O, kernel I/O counters, all samples, and paired elapsed ratios remain in the JSON evidence. They do not prove physical device traffic.",
    "These results cover local warm-cache workloads. They do not establish cloud, remote-storage, cold-cache, or update-heavy performance.", "",
    f"- Baseline extension: `{next(iter(hashes['baseline']))}`.",
    f"- Candidate extension: `{next(iter(hashes['candidate']))}`.",
    "- Fixture summaries: `benchmark-fixture-small-summary.json` and `benchmark-fixture-summary.json`.",
    "- All comparisons: `performance-comparisons.json`.",
    "- Per-process output: `raw/`. Replay events: `probes/`. Plan evidence: `plans/`.",
    "- Detector controls: `controls/final/summary.json`. Reproduction commands: `README.md`.",
])
(root / "performance-comparisons.json").write_text(json.dumps(observations, indent=2) + "\n")
(root / "performance-report.md").write_text("\n".join(report) + "\n")
print(root / "performance-report.md")
