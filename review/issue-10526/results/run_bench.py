import json
import os
import statistics
import subprocess
from pathlib import Path

P2 = Path("/dev/shm/lance-10526/shared-buffer-matched-final/p2")
IPC = Path("/dev/shm/lance-10526/ipc")
BENCH_PY = "/root/lance/tmp/10526-review/review/issue-10526/linux-64cpu/bench.py"
TAKE_PY = "/root/lance/tmp/shared-buffer-tools/take.py"

PYTHONS = {
    "base": "/root/lance/tmp/shared-buffer-matched-final/env-00/bin/python",
    "pr1": "/root/lance/tmp/lance-pr1-rerun-d4cac03/env-head/bin/python",
    "killer": "/tmp/killer-proto/venv/bin/python",
    "killer_on_base": "/tmp/killer-proto/venv/bin/python",
}


def clean_env():
    env = os.environ.copy()
    for k in list(env.keys()):
        if k.startswith("MALLOC_") or k in (
            "LANCE_FILE_WRITER_MAX_PAGE_BYTES",
            "PYTHONPATH",
            "PYTHONHOME",
            "VIRTUAL_ENV",
        ):
            env.pop(k, None)
    env["LANCE_CPU_THREADS"] = "64"
    return env


ENV = clean_env()


def run_bench_read(build, ds, op):
    variant = "base" if build in ("base", "killer_on_base") else "final"
    out = subprocess.check_output(
        [
            PYTHONS[build],
            "-B",
            BENCH_PY,
            "read",
            str(P2 / ds / variant),
            str(IPC / f"{ds}.arrow"),
            op,
        ],
        env=ENV,
        text=True,
    )
    row = json.loads(out.strip().splitlines()[-1])
    return {
        "wall_ms": row["wall_seconds"] * 1000.0,
        "rss_mib": row["process_peak_rss_kib"] / 1024.0,
    }


def run_take_repeat(build, ds, count, ds_rows, repeat):
    variant = "base" if build in ("base", "killer_on_base") else "final"
    out = subprocess.check_output(
        [
            PYTHONS[build],
            "-B",
            TAKE_PY,
            str(P2 / ds / variant),
            str(count),
            "--dataset-rows",
            str(ds_rows),
            "--take-only",
            "--repeat",
            str(repeat),
        ],
        env=ENV,
        text=True,
    )
    lines = [json.loads(line) for line in out.strip().splitlines()]
    return lines


def summarize(vals):
    s = sorted(vals)
    return {
        "median": statistics.median(s),
        "min": s[0],
        "max": s[-1],
    }


def bench_read_case(ds, op, trials, builds=("base", "pr1", "killer")):
    per_build = {b: {"wall_ms": [], "rss_mib": []} for b in builds}
    for t in range(trials):
        for b in builds:
            res = run_bench_read(b, ds, op)
            per_build[b]["wall_ms"].append(res["wall_ms"])
            per_build[b]["rss_mib"].append(res["rss_mib"])
    summary = {
        b: {
            "wall_ms": summarize(per_build[b]["wall_ms"]),
            "rss_mib": summarize(per_build[b]["rss_mib"]),
        }
        for b in builds
    }
    print(
        f"[READ] {ds} {op} (N={trials}): "
        + " | ".join(
            f"{b}: {summary[b]['wall_ms']['median']:.2f}ms ({summary[b]['rss_mib']['median']:.2f}MiB)"
            for b in builds
        ),
        flush=True,
    )
    return summary


def bench_repeat_case(
    ds,
    ds_rows,
    count,
    repeat,
    warm_slice_start,
    trials,
    builds=("base", "pr1", "killer"),
):
    per_build = {
        b: {"first_ms": [], "warm_ms": [], "proc_rss_mib": [], "first_rss_mib": []}
        for b in builds
    }
    for t in range(trials):
        for b in builds:
            lines = run_take_repeat(b, ds, count, ds_rows, repeat)
            first = lines[0]["take_ms"]
            warm = statistics.median(x["take_ms"] for x in lines[warm_slice_start:])
            first_rss = lines[0]["process_peak_rss_kib"] / 1024.0
            proc_rss = max(x["process_peak_rss_kib"] for x in lines) / 1024.0
            per_build[b]["first_ms"].append(first)
            per_build[b]["warm_ms"].append(warm)
            per_build[b]["first_rss_mib"].append(first_rss)
            per_build[b]["proc_rss_mib"].append(proc_rss)
    summary = {b: {k: summarize(v) for k, v in per_build[b].items()} for b in builds}
    print(
        f"[REPEAT] {ds} take({count}) repeat={repeat} warm[{warm_slice_start + 1}..{repeat}] (N={trials}): "
        + " | ".join(
            f"{b}: first={summary[b]['first_ms']['median']:.2f}ms warm={summary[b]['warm_ms']['median']:.2f}ms procRSS={summary[b]['proc_rss_mib']['median']:.2f}MiB"
            for b in builds
        ),
        flush=True,
    )
    return summary


results = {"read": {}, "repeat": {}}

# 1. Core datasets with regressions + all others from screenshot
read_cases = [
    ("wide-unique", "scan", 7),
    ("wide-unique", "take", 5),
    ("wide-repeated", "scan", 7),
    ("wide-repeated", "take", 5),
    ("wide-clustered", "scan", 7),
    ("wide-clustered", "take", 5),
    ("wide-unique-8k", "scan", 5),
    ("wide-unique-8k", "take", 5),
    ("wide-template", "scan", 5),
    ("wide-template", "take", 5),
    ("wide-mixed", "scan", 5),
    ("wide-mixed", "take", 5),
]

for ds, op, trials in read_cases:
    results["read"][f"{ds}:{op}"] = bench_read_case(ds, op, trials)

# 2. Repeat benchmarks (default glibc)
results["repeat"]["wide-unique:1024"] = bench_repeat_case(
    "wide-unique",
    25000,
    1024,
    20,
    5,
    5,
    builds=("base", "pr1", "killer", "killer_on_base"),
)
results["repeat"]["wide-unique:128"] = bench_repeat_case(
    "wide-unique",
    25000,
    128,
    20,
    5,
    5,
    builds=("base", "pr1", "killer"),
)
results["repeat"]["wide-repeated:128"] = bench_repeat_case(
    "wide-repeated",
    8000,
    128,
    10,
    2,
    5,
    builds=("base", "pr1", "killer"),
)
results["repeat"]["wide-clustered:128"] = bench_repeat_case(
    "wide-clustered",
    25000,
    128,
    10,
    2,
    5,
    builds=("base", "pr1", "killer"),
)

out_path = Path("/tmp/killer-proto/tmp/bench_results.json")
out_path.write_text(json.dumps(results, indent=2))
print("DONE, saved to", out_path, flush=True)
