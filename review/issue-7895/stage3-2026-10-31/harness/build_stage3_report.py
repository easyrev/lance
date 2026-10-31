#!/usr/bin/env python3
"""Build the Stage 3 Markdown report from saved JSON results."""

from __future__ import annotations

import json
import re
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path("/mnt/lance/9617-bench")
RESULTS = ROOT / "results"
GIB = 1024**3


def read(path: Path):
    return json.loads(path.read_text())


def mark(spread: float) -> str:
    return "*" if spread > 10 else ""


def stat_text(metric: dict, scale: float = 1.0, digits: int = 3) -> str:
    median = metric["median"] / scale
    minimum = metric["min"] / scale
    maximum = metric["max"] / scale
    suffix = mark(metric["spread_pct"])
    return (
        f"{median:.{digits}f} [{minimum:.{digits}f}-"
        f"{maximum:.{digits}f}]{suffix}"
    )


def failure_count(outer: dict) -> int:
    return 1 if outer.get("status") != "ok" else 0


def grouped_runs(pattern: str) -> dict:
    grouped: dict[str, list[dict]] = {}
    for path in RESULTS.glob(pattern):
        grouped.setdefault(path.stem, []).append(read(path))
    return grouped


def summary_metric(values: list[dict], getter) -> dict | None:
    samples = [float(getter(value)) for value in values if value.get("status") == "ok"]
    if not samples:
        return None
    median = statistics.median(samples)
    return {
        "median": median,
        "min": min(samples),
        "max": max(samples),
        "spread_pct": (
            (max(samples) - min(samples)) / median * 100 if median else 0
        ),
    }


def exp12_table(conflict: bool) -> str:
    summary = read(RESULTS / "experiments-1-2-summary.json")
    rows = [row for row in summary if row["key"][3] is conflict]

    def sort_key(row):
        case = row["key"][1]
        size = int(case.split("gib", 1)[0])
        source = case.split("-", 1)[1]
        return size, source, row["key"][2]

    rows.sort(key=sort_key)
    lines = [
        "| Size | Source | Build | Runs | Wall s | CPU s | Peak RSS GiB | Spill GiB |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        case = row["key"][1]
        size = int(case.split("gib", 1)[0])
        source = case.split("-", 1)[1]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(size),
                    source,
                    row["key"][2],
                    str(row["runs"]),
                    stat_text(row["wall_s"], digits=3),
                    stat_text(row["cpu_total_s"], digits=3),
                    stat_text(row["peak_rss_bytes"], GIB, 3),
                    stat_text(row["spill_peak_bytes"], GIB, 3),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def exp1_plan_table() -> str:
    paths = sorted(RESULTS.glob("exp1-analyze-*.plan.json"))
    rows = []
    for path in paths:
        data = read(path)
        name = path.stem.removesuffix(".plan")
        size = int(name.split("-")[2].removesuffix("gib"))
        source = name.split("-")[3]
        build = name.split("-")[4]
        rows.append((size, source, build, data))
    rows.sort(key=lambda item: (item[0], item[1], item[2]))
    lines = [
        "| Size | Source | Build | Join | Build side | Build rows | Build memory | Source plan |",
        "|---:|---|---|---|---|---:|---:|---|",
    ]
    for size, source, build, data in rows:
        source_plan = (
            "LanceRead" if data["native_source_read"] else "reader factory"
        )
        lines.append(
            f"| {size} | {source} | {build} | {data['join_mode']} / "
            f"{data['join_type']} | {data['build_side']} | "
            f"{data['build_input_rows_text']} | "
                    f"{data['build_mem_used_bytes'] / GIB:.3f} GiB | "
                    f"{source_plan} |"
        )
    return "\n".join(lines)


def cold_table() -> str:
    rows = read(RESULTS / "cold-cache-summary.json")
    rows.sort(key=lambda row: (row["case"].split("-")[0], row["build"]))
    lines = [
        "| Source | Build | Runs | Wall s | CPU s | Peak RSS GiB | Spill GiB |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case'].split('-', 1)[1]} | {row['build']} | "
            f"{row['runs']} | {stat_text(row['wall_s'])} | "
            f"{stat_text(row['cpu_total_s'])} | "
            f"{stat_text(row['peak_rss_bytes'], GIB)} | "
            f"{stat_text(row['spill_peak_bytes'], GIB)} |"
        )
    return "\n".join(lines)


def exp3_data() -> tuple[list[dict], dict]:
    tag_pattern = re.compile(
        r"^exp3-(run|cap)-(?P<rows>\d+)-(?P<build>U|P1|P2)-r(?P<run>\d+)$"
    )
    rows = []
    for path in RESULTS.glob("exp3-run-*.json"):
        match = tag_pattern.match(path.stem)
        if not match:
            continue
        outer = read(path)
        rows.append(
            {
                "kind": "normal",
                "rows": int(match["rows"]),
                "build": match["build"],
                "outer": outer,
            }
        )
    for path in RESULTS.glob("exp3-cap-*.json"):
        match = tag_pattern.match(path.stem)
        if not match:
            continue
        outer = read(path)
        rows.append(
            {
                "kind": "cap16",
                "rows": int(match["rows"]),
                "build": match["build"],
                "outer": outer,
            }
        )

    grouped = {}
    for row in rows:
        key = (row["kind"], row["rows"], row["build"])
        grouped.setdefault(key, []).append(row["outer"])

    plans = {}
    for path in RESULTS.glob("exp3-analyze-*.plan.json"):
        data = read(path)
        match = re.search(r"exp3-analyze-(\d+)-(U|P1|P2)", path.stem)
        if match:
            plans[(int(match.group(1)), match.group(2))] = data
    return rows, {"grouped": grouped, "plans": plans}


def exp3_tables() -> tuple[str, str]:
    _, data = exp3_data()
    groups = data["grouped"]
    plans = data["plans"]
    lines = [
        "| Rows | Build | Condition | Runs OK | Wall s | CPU s | Peak RSS GiB | Build side | Build memory |",
        "|---:|---|---|---:|---:|---:|---:|---|---:|",
    ]
    for (kind, rows, build), values in sorted(groups.items()):
        if kind != "normal":
            continue
        successes = [value for value in values if value.get("status") == "ok"]
        wall = summary_metric(values, lambda value: value["child"]["wall_s"])
        cpu = summary_metric(values, lambda value: value["cpu_total_s"])
        rss = summary_metric(values, lambda value: value["peak_rss_kib"] * 1024)
        plan = plans.get((rows, build))
        condition = "uncapped"
        if build == "P1" and rows == 16_000_000:
            condition = "56 GiB safety cap"
        build_side = plan["build_side"] if plan else "OOM before plan"
        build_memory = (
            f"{plan['build_mem_used_bytes'] / GIB:.3f} GiB"
            if plan
            else "unavailable"
        )
        lines.append(
            f"| {rows:,} | {build} | {condition} | "
            f"{len(successes)}/{len(values)} | "
            f"{stat_text(wall) if wall else 'OOM'} | "
            f"{stat_text(cpu) if cpu else 'OOM'} | "
            f"{stat_text(rss, GIB) if rss else 'OOM'} | "
            f"{build_side} | {build_memory} |"
        )

    cap_lines = [
        "| Rows | Build | Cap | Runs OK | Wall s | CPU s | Peak RSS GiB |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for (kind, rows, build), values in sorted(groups.items()):
        if kind != "cap16":
            continue
        successes = [value for value in values if value.get("status") == "ok"]
        wall = summary_metric(values, lambda value: value["child"]["wall_s"])
        cpu = summary_metric(values, lambda value: value["cpu_total_s"])
        rss = summary_metric(values, lambda value: value["peak_rss_kib"] * 1024)
        cap_lines.append(
            f"| {rows:,} | {build} | 16 GiB | "
            f"{len(successes)}/{len(values)} | "
            f"{stat_text(wall) if wall else 'OOM'} | "
            f"{stat_text(cpu) if cpu else 'OOM'} | "
            f"{stat_text(rss, GIB) if rss else 'OOM'} |"
        )
    return "\n".join(lines), "\n".join(cap_lines)


def exp4_table() -> str:
    rows = read(RESULTS / "experiment4-summary.json")
    rows.sort(key=lambda row: (row["case"], row["build"], row["conflict"]))
    lines = [
        "| Source | Build | Conflict | Runs | Wall s | CPU s | Peak RSS GiB | Spill GiB | Received GB |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case'].removeprefix('oss-')} | {row['build']} | "
            f"{'yes' if row['conflict'] else 'no'} | "
            f"{row['successes']}/{row['attempts']} | "
            f"{stat_text(row['wall_s'])} | {stat_text(row['cpu_total_s'])} | "
            f"{stat_text(row['peak_rss_bytes'], GIB)} | "
            f"{stat_text(row['spill_peak_bytes'], GIB)} | "
            f"{stat_text(row['received_bytes'], 1e9)} |"
        )
    return "\n".join(lines)


def exp5_table() -> str:
    pattern = re.compile(r"^exp5-run-(?P<size>\d+)gib-(?P<build>U|P2)-r(?P<run>\d+)$")
    groups = {}
    for path in RESULTS.glob("exp5-run-*.json"):
        match = pattern.match(path.stem)
        if not match:
            continue
        key = (int(match["size"]), match["build"])
        groups.setdefault(key, []).append(read(path))
    lines = [
        "| Source GiB | Build | Runs OK | Wall s | CPU s | Peak RSS GiB | Spill peak GiB | Result |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for (size, build), values in sorted(groups.items()):
        successes = [value for value in values if value.get("status") == "ok"]
        wall = summary_metric(values, lambda value: value["child"]["wall_s"])
        cpu = summary_metric(values, lambda value: value["cpu_total_s"])
        rss = summary_metric(values, lambda value: value["peak_rss_kib"] * 1024)
        spill = summary_metric(
            values,
            lambda value: value["child"].get("spill_peak_bytes", 0),
        )
        if spill is None:
            spill_values = [
                value["child"].get("spill_peak_bytes", 0)
                for value in values
                if value.get("child")
            ]
            spill = (
                {
                    "median": statistics.median(spill_values),
                    "min": min(spill_values),
                    "max": max(spill_values),
                    "spread_pct": 0,
                }
                if spill_values
                else None
            )
        if successes:
            outcome = "success"
        else:
            outcome = "ENOSPC"
        lines.append(
            f"| {size} | {build} | {len(successes)}/{len(values)} | "
            f"{stat_text(wall) if wall else 'failed'} | "
            f"{stat_text(cpu) if cpu else 'failed'} | "
            f"{stat_text(rss, GIB) if rss else 'failed'} | "
            f"{stat_text(spill, GIB) if spill else 'n/a'} | {outcome} |"
        )
    return "\n".join(lines)


def variant_table() -> str:
    data = read(RESULTS / "parquet-variants-summary.json")
    lines = [
        "| Size | Conflict | Setting | Peak RSS GiB | Wall s | CPU s | Qualifies |",
        "|---:|---|---|---:|---:|---:|---|",
    ]
    for row in data["comparison"]:
        for key, label in (
            ("current", "current"),
            ("U", "U reference"),
            ("readahead_1", "a: readahead=1"),
            ("byte_budget", "b: 64 MiB budget"),
        ):
            metrics = row[key]
            qualification = ""
            if key in ("readahead_1", "byte_budget"):
                qualification = (
                    "yes" if row[f"{key}_qualifies"] else "no"
                )
            lines.append(
                f"| {row['size_gib']} | {'yes' if row['conflict'] else 'no'} | "
                f"{label} | {stat_text(metrics['peak_rss_bytes'], GIB)} | "
                f"{stat_text(metrics['wall_s'])} | "
                f"{stat_text(metrics['cpu_total_s'])} | {qualification} |"
            )
    return "\n".join(lines)


def main() -> int:
    exp3_normal, exp3_cap = exp3_tables()
    report = f"""# #9617 Stage 3 benchmark report

## Outcome

Stage 2b passed with rule (a).
U, P1, and P2 used the recorded `release` wheels from the preflight.
I rebuilt no wheel and needed no profiling wheel.

All planned local, OSS, loop-temp, cold-cache, and scanner-variant cells ran.
The repository remains clean at `9767241c21d4124dc2f8d24d642abe93c8ca859c`.
I made no commit 3 because no scanner variant met every selection condition.
I did not push and did not post GitHub comments.

A host OOM killed the first 16M P1 attempt.
I resumed with a 56 GiB P1 safety cap and preserved the OOM result.

Metrics are `median [min-max]`.
A `*` marks a metric with spread above 10%.

## Environment

| Item | Value |
|---|---|
| CPU | AMD EPYC 9T25, 16 vCPUs |
| Memory | 61 GiB |
| Swap | None |
| OS | Ubuntu 24.04.5 LTS |
| Kernel | 6.8.0-139-generic |
| Data device | `/dev/nvme0n1`, 400 GB |
| Data filesystem | ext4, 393 GiB |
| Device model | Alibaba Cloud Elastic Block Storage over NVMe |
| Python | 3.12.3 |
| Lance | 15.0.0b7 |
| PyArrow | 25.0.1 |
| NumPy | 2.5.4 |

The data volume is a whole-disk ext4 filesystem and has no partition table.
`resize2fs` grew it online from 315.9 GB to 421.6 GB.
The gate had 170.63 GiB free and an estimated peak of 88 GiB.

## Builds

The preflight build used `maturin build --release`.

| Build | Commit | Wheel SHA256 |
|---|---|---|
| U | `f9a5c662d79ac312d16d8f636cb1feba4e84aee8` | `e6b3c0b15f816027d757430cca09b7b08b92ebc0e67d905b30cd5e65ea33d6fc` |
| P1 | `15a523ffcc93e6d2c73ad2af69a1e6420efcdc22` | `28e861a077701abbbf97a924525bf6ab1d70c06674bc1bfe4874e0917294d73a` |
| P2 | `9767241c21d4124dc2f8d24d642abe93c8ca859c` | `5b9945c84d399258ebe04d7a5cad604f03d846666d76559458e0e3aa8e478e05` |

## Experiment 1

Target: 4M rows, full schema, about 12 GiB.
Sources: 1, 4, and 16 GiB, Lance and Parquet, 50% updates and 50% inserts.
Runs: 5 at 1 and 4 GiB, 3 at 16 GiB.

{exp12_table(False)}

P1 and P2 used no replay spill in every full-schema cell.
U spilled the full source size.

### Experiment 1 plans

{exp1_plan_table()}

The P2 full-schema Lance build side matched P1 at every size.
All three full-schema Lance plans built the target side.
The P2 check therefore passed.

### Cold cache

The 4 GiB subset dropped page caches before every run.

{cold_table()}

## Experiment 2

Each run made one competing target update before the stale-handle merge.
Use CPU and peak RSS for conflict comparisons.
Wall time includes randomized retry backoff and is informational.

{exp12_table(True)}

All 36 cells completed after I increased the artificial retry window from 30 seconds to 30 minutes.
The original 30-second and 10-minute harness limits expired before valid 16 GiB retries completed.

### Noise floor

Experiment 2 used the same Parquet path for P1 and P2 at 16 GiB.

| Build | Wall s | CPU s | Peak RSS GiB |
|---|---:|---:|---:|
| P1 | 473.670 [326.576-545.131] | 152.096 [110.246-175.206] | 29.590 [23.678-35.964] |
| P2 | 381.805 [279.393-472.299] | 151.437 [137.897-173.880] | 33.293 [29.168-38.349] |

The P1/P2 median differences were 91.865 s wall, 3.702 GiB RSS, and 0.659 s CPU.
These are 21.5%, 11.8%, and 0.4% of the mean values.
The ranges overlap, so these differences are noise.

For hot-cache 16 GiB cells, assume about 35% wall noise, 30% CPU noise, and 25% RSS noise.
Use cold-cache runs for decisions near those bands.

## Experiment 3

The source has 100K matching partial rows.
The target uses Auto write mode, which selected RewriteRows.

{exp3_normal}

{exp3_cap}

The smallest P1 OOM is 4M rows under the 16 GiB cap.
All three P1 attempts exited with code 137.
P2 completed all three 4M attempts with a median peak RSS of 8.23 GiB.

P1 `analyze_plan` at 16M rows also exceeded a 56 GiB safety cap.
P2 used the source side, 100K build rows, and about 0.005 GiB of build memory at every size.
The 16M P1 target build requires about 50 GiB before other allocations.

## Full-schema Lance follow-up

P1 uses one `StreamingTableExec` source partition.
P2 uses a native `LanceRead` over six fragments.
Both plans emit 676 source batches before the 16-way hash repartition.
The plans do not expose a different batch size or readahead setting.

| Cache | Build | Wall s | CPU s | Peak RSS GiB | Read GiB/s |
|---|---|---|---:|---:|---:|
| Hot | P1 | 25.330 [24.379-61.516] | 41.440 [38.439-42.401] | 9.231 [8.741-10.717] | cached |
| Hot | P2 | 30.978 [25.971-43.879] | 44.229 [43.954-45.258] | 11.936 [11.429-12.694] | cached |
| Hot | P2, 64 MiB bound | 25.831 [25.481-25.866] | 44.492 [43.828-44.668] | 10.263 [9.649-11.588] | cached |
| Cold | P1 | 161.927 [159.939-164.719] | 30.429 [30.147-30.801] | 3.553 [3.437-3.648] | 0.0978 [0.0969-0.0998] |
| Cold | P2 | 165.444 [163.619-165.730] | 30.638 [30.209-30.933] | 4.881 [3.574-4.954] | 0.0965 [0.0963-0.0975] |
| Cold | P2, 64 MiB bound | 165.200 [163.945-165.436] | 30.286 [30.155-30.395] | 3.894 [3.511-4.105] | 0.0967 [0.0965-0.0974] |

The cold runs read 15.96 GiB from the backing device in every build.
They used the same disk throughput and CPU time within about 3%.

The evidence rejects the hypothesis.
The native path can issue fragment reads with more concurrency, but the measured backing-device throughput did not increase.
The earlier 139 s versus 68 s result did not reproduce.
The follow-up hot medians were 25.33 s for P1 and 30.98 s for P2.

I built one local, uncommitted P2 variant with `with_batch_size_bytes(64 MiB)`.
The patch is `{ROOT}/followup/patches/native-source-64mib.patch`.
The wheel SHA256 is `60a1f1e3f69df937c5f7f7d94f54136b047f39751b8d8b93b188fef930adc539`.
The PR tree is clean again.

At cold cache, the bound recovered 74% of the P2-to-P1 RSS gap.
The P2-to-P1 gap fell from 1.328 GiB to 0.341 GiB.
Wall time changed by 0.15% versus P2 and stayed within 2.1% of P1.
CPU and disk throughput stayed within 1% and 2%.

## Upstream retry default

U used the default 10 retries and 30-second retry timeout.
The 16 GiB Lance source received one forced competing update.

The first attempt took 115.217 s.
It wrote a 16.492 GiB replay spill.
It returned `retry_timeout` after attempted 1 time.
U did not start a second attempt.
Peak RSS was 9.252 GiB and CPU time was 52.103 s.

## Experiment 4

OSS used Lance native `oss://` on the internal endpoint.
PyArrow used the S3-compatible internal endpoint with virtual addressing.
All children loaded `/root/.lance-bench/oss.env` themselves.
Credentials did not appear in logs or JSON.

{exp4_table()}

All 24 OSS cells completed.
I removed the 16 uploaded files after the experiment.

## Experiment 5

`modprobe loop` created usable loop devices.
I mounted `TMPDIR` as a 4 GiB ext4 filesystem on `/dev/loop0`.
I did not use a memory cap for this experiment.

{exp5_table()}

U failed all 4 and 16 GiB cells with ENOSPC.
P2 completed all cells with zero replay spill.

## Parquet scan parameters

The variants were local, uncommitted monkey patches in the child process.
The harness measured the current and variant settings three times per condition.

{variant_table()}

Variant (a) failed RSS at 4 GiB conflict and both 16 GiB cases.
It also exceeded the 5% CPU limit at 16 GiB no conflict.
Variant (b) failed the 5% wall-time limit at 16 GiB no conflict.
It also failed the U RSS limit at 16 GiB conflict.

No variant qualifies.
I kept the current scanner settings and made no commit 3.

## Contradictions and findings

The no-conflict full-schema hardware was not stable across repetitions.
Many wall, RSS, and CPU spreads exceed 10%.
The first run in several cells was much slower than later runs.
The cold-cache subset was more stable than the hot-cache subset.

Parquet did not behave as a P1/P2 control.
The current P2 Parquet source exceeded U RSS in three of four measured conditions.
It stayed below U only at 16 GiB without a conflict.
Variant (b) improves that peak but does not satisfy every case.

P2's native source removes replay spill and sharply lowers partial-update memory.
At 8M wide rows, P1 used 49.77 GiB RSS and P2 used 7.17 GiB.

P1 can OOM even without the requested 16 GiB cap.
At 16M rows it exceeded the 56 GiB safety cap in all three normal attempts.

## Five strongest numbers

| Number | Exact condition |
|---:|---|
| 16.49 GiB | U replay spill, 16 GiB Lance source, no conflict, 4M target. |
| 49.77 GiB vs 7.17 GiB | P1 vs P2 median peak RSS, 8M wide target, 100K matching rows, auto RewriteRows. |
| 4M | Smallest P1 OOM with a 16 GiB cap. P2 completed all three attempts. |
| 3.84 GiB | U peak spill before ENOSPC on the 4 GiB loop filesystem. P2 used 0 bytes. |
| 154.93 s vs 95.07 s | Variant (b) vs current wall time, 16 GiB Parquet source, no conflict. The 5% limit failed. |

## Raw data

Raw JSON, plans, and logs are under `/mnt/lance/9617-bench/results`, `/mnt/lance/9617-bench/plans`, and `/mnt/lance/9617-bench/logs`.
"""
    target = ROOT / "report-stage3.md"
    target.write_text(report)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
