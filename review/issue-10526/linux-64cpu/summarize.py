#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from statistics import median

from bench import DATASETS

raw = Path(sys.argv[1])
assert (raw / "measure.exit").read_text().strip() == "0"


def read_json(stem):
    return json.loads((raw / f"{stem}.json").read_text())


def comparison(name, baseline, final, limit=None, suffix=""):
    ratio = final / baseline if baseline else None
    delta = f", {(ratio - 1):+.2%}" if ratio is not None else ""
    missed = limit is not None and final > baseline * (1 + limit)
    status = " **MISS**" if missed else ""
    if missed:
        misses.append(name)
    return f"{baseline:,.3f} → {final:,.3f}{suffix}{delta}{status}"


def file_summary(result):
    return (
        f"{result['file_bytes']:,} B, {result['pages']} pages, "
        f"{result['max_uncompressed_value_bytes']:,} / "
        f"{result['max_encoded_page_bytes']:,} B"
    )


def repeat(stem, variant):
    return [read_json(f"{stem}-{trial}-{variant}") for trial in (1, 2, 3)]


def compare_metric(name, runs, key, limit=None, divisor=1, suffix=""):
    baseline, final = (median(run[key] / divisor for run in group) for group in runs)
    return comparison(name, baseline, final, limit, suffix)


misses = []
variants = ("baseline", "fix")
print((raw / "criteria.md").read_text())
print(
    "Baseline → final. Time and RSS are medians except for single file-stage writes. "
    "Max page sizes are logical value payload bytes / sum of encoded page buffers. "
    "Per-page encoding details and all trial values are in the raw JSON."
)
print()
print("| Case | File or timing | Peak RSS (GiB) | Other |")
print("| --- | --- | --- | --- |")
for dataset in DATASETS:
    baseline, final = (read_json(f"file-{dataset}-{variant}") for variant in variants)
    file_comp = comparison(
        f"{dataset} file size", baseline["file_bytes"], final["file_bytes"], 0.02
    )
    rss = comparison(
        f"{dataset} file write RSS",
        baseline["process_peak_rss_kib"] / 1024**2,
        final["process_peak_rss_kib"] / 1024**2,
        0.10,
    )
    print(
        f"| {dataset} file | {file_summary(baseline)} → {file_summary(final)} "
        f"| {rss} | {file_comp} B, exact round trips |"
    )
    for operation in ("scan", "take"):
        case = f"{dataset} {operation}"
        runs = [repeat(f"{operation}-{dataset}", variant) for variant in variants]
        if operation == "take":
            assert all(
                run["indices"] == runs[0][0]["indices"]
                for group in runs
                for run in group
            )
        wall = compare_metric(case, runs, "wall_seconds", divisor=0.001, suffix=" ms")
        rss = compare_metric(f"{case} RSS", runs, "process_peak_rss_kib", 0.10, 1024**2)
        print(f"| {case} | {wall} | {rss} | |")

for dataset, writers, threads in (
    ("wide-unique", 1, 8),
    ("wide-unique", 1, 64),
    ("wide-unique-8k", 8, 8),
    ("wide-unique-8k", 8, 64),
    ("wide-clustered", 1, 64),
    ("wide-mixed", 1, 64),
):
    case = f"{dataset} write, {writers} writer(s) × {threads} threads"
    runs = [
        repeat(f"write-{dataset}-{writers}-{threads}", variant) for variant in variants
    ]
    wall = compare_metric(
        f"{case} wall time", runs, "write_wall_seconds", 0.10, suffix=" s"
    )
    rss = compare_metric(f"{case} RSS", runs, "process_peak_rss_kib", 0.10, 1024**2)
    cpu = compare_metric(case, runs, "write_cpu_seconds", suffix=" s CPU")
    before = compare_metric(
        case, runs, "pre_write_rss_kib", divisor=1024**2, suffix=" GiB pre-write"
    )
    throughput = [
        median(
            run["rows_per_writer"] * run["writers"] / run["write_wall_seconds"]
            for run in group
        )
        for group in runs
    ]
    rate = comparison(case, *throughput, suffix=" rows/s")
    print(f"| {case} | {wall} | {rss} | {cpu}<br>{before}<br>{rate} |")

print()
print(f"Threshold misses ({len(misses)})")
print()
for miss in misses:
    print(f"- {miss}")
