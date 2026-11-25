import json
import statistics
import sys
from pathlib import Path

raw = Path(sys.argv[1])
builds = ("base", "final", "exp-A", "exp-B")
titles = (
    "base (1p)",
    "final (135p / 44p)",
    "exp-A (exact reserve)",
    "exp-B (page bridging)",
)
trials = range(1, 4)


def load(name):
    return json.loads((raw / name).read_text())


def stats(values):
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def summarize_takes(count):
    common_indices = None
    summaries = {}
    for build in builds:
        processes = [
            [
                json.loads(line)
                for line in (raw / f"repeat-{count}-{trial}-{build}.jsonl")
                .read_text()
                .splitlines()
            ]
            for trial in trials
        ]
        for process in processes:
            assert len(process) == 20, (build, count, len(process))
            for iteration in process:
                if common_indices is None:
                    common_indices = iteration["indices"]
                assert len(common_indices) == iteration["rows"] == count
                assert iteration["indices"] == common_indices
            assert all(
                start["process_peak_rss_kib"] <= end["process_peak_rss_kib"]
                for start, end in zip(process, process[1:])
            )
        summaries[build] = {}
        for name, selected in (
            ("first", slice(0, 1)),
            ("second", slice(1, 2)),
            ("steady", slice(5, 20)),
        ):
            chosen = [
                iteration for process in processes for iteration in process[selected]
            ]
            summaries[build][name] = {
                "latency_ms": stats([result["take_ms"] for result in chosen]),
                "median_of_process_medians_ms": statistics.median(
                    statistics.median(
                        [result["take_ms"] for result in process[selected]]
                    )
                    for process in processes
                ),
                "rss_kib": stats([result["process_peak_rss_kib"] for result in chosen]),
                "samples": len(chosen),
            }
        summaries[build]["process_peak_rss_kib"] = stats(
            [process[-1]["process_peak_rss_kib"] for process in processes]
        )
    return summaries


def summarize_read(kind, operation):
    summaries = {}
    common_indices = None
    for build in builds:
        results = [load(f"{operation}-{kind}-{trial}-{build}.json") for trial in trials]
        for result in results:
            assert (result["dataset"], result["operation"]) == (kind, operation)
            if operation == "take":
                if common_indices is None:
                    common_indices = result["indices"]
                assert result["indices"] == common_indices
        summaries[build] = {
            "latency_ms": stats([result["wall_seconds"] * 1000 for result in results]),
            "rss_kib": stats([result["process_peak_rss_kib"] for result in results]),
        }
    return summaries


def show(metric, scale=1):
    median, low, high = (metric[key] / scale for key in ("median", "min", "max"))
    return f"{median:.3f} [{low:.3f}–{high:.3f}]"


def show_delta(before, after, unit, scale=1):
    before = before["median"] / scale
    after = after["median"] / scale
    return f"{after - before:+.3f} {unit} ({(after / before - 1) * 100:+.2f}%)"


def output_row(label, values):
    print("| " + " | ".join([label, *values]) + " |")


repeated = {count: summarize_takes(count) for count in (128, 1024)}
standalone = {
    f"{kind} {operation}": summarize_read(kind, operation)
    for kind, operation in (
        ("wide-unique-8k", "scan"),
        ("wide-unique-8k", "take"),
        ("wide-unique", "scan"),
    )
}
if len(sys.argv) == 3:
    Path(sys.argv[2]).write_text(
        json.dumps({"repeated_take": repeated, "standalone": standalone}, indent=2)
        + "\n"
    )

print("""# Issue 10526 follow-up decode measurements

[Scripts, raw trials and SHA256SUMS](decode-followup/) · [Original results](summary.md)

## Methods

Each cell reports median [minimum–maximum]. Each mode used three fresh processes
with `LANCE_CPU_THREADS=64`, the `release-with-debug` profile, and separate baseline,
final and experiment environments and targets. The experiment target and environment
were reused sequentially for A and B. The raw records include the machine configuration,
dataset file hashes and page counts.

For repeated `take`, each process opened one dataset handle before timing and
selected the same sorted row numbers from NumPy seed 10526 in all 20 calls.
Cold refers to the first take on that handle with the dataset on tmpfs.
The steady-state latency and RSS summaries pool calls 6–20 (45 samples).
The generated JSON also records the median of the three process medians.
RSS is the process high-water mark observed at the end of each call. The
final RSS row summarizes the high-water mark at the end of all 20 calls.
Standalone reads include dataset open, with `batch_size=1024` for scans.

The earlier run's Arrow IPC inputs were reused. The original writer rebuilt the Lance
files. A and B read the same final files as this round's final trials.
""")
print("## Builds\n")
print("| Build | Commit | Imported Python extension SHA-256 |")
print("| --- | --- | --- |")
for build, title in zip(builds, titles):
    sha = (raw / f"commit-{build}.txt").read_text().strip()
    extension = (raw / f"extension-{build}.sha256").read_text().split()[0]
    output_row(title, [f"`{sha}`", f"`{extension}`"])
print("\n## Four-build comparison\n")
output_row("Metric", titles)
output_row("---", ["---:"] * len(builds))
for count, summaries in repeated.items():
    for key, label in (
        ("first", "call 1"),
        ("second", "call 2"),
        ("steady", "calls 6–20"),
    ):
        output_row(
            f"wide-unique take({count}) {label}, ms",
            [show(summaries[build][key]["latency_ms"]) for build in builds],
        )
        output_row(
            f"wide-unique take({count}) {label} peak RSS, MiB",
            [show(summaries[build][key]["rss_kib"], 1024) for build in builds],
        )
    output_row(
        f"wide-unique take({count}) process peak RSS, MiB",
        [show(summaries[build]["process_peak_rss_kib"], 1024) for build in builds],
    )
for label, summaries in standalone.items():
    output_row(
        f"{label}, ms", [show(summaries[build]["latency_ms"]) for build in builds]
    )
    output_row(
        f"{label} peak RSS, MiB",
        [show(summaries[build]["rss_kib"], 1024) for build in builds],
    )

changes = (
    ("base", "final"),
    ("final", "exp-A"),
    ("exp-A", "exp-B"),
    ("final", "exp-B"),
)
print("\n## Median changes\n")
output_row("Metric", [f"{before} → {after}" for before, after in changes])
output_row("---", ["---:"] * len(changes))
for count, summaries in repeated.items():
    for key, label in (
        ("first", "call 1"),
        ("second", "call 2"),
        ("steady", "calls 6–20"),
    ):
        output_row(
            f"wide-unique take({count}) {label}",
            [
                show_delta(
                    summaries[before][key]["latency_ms"],
                    summaries[after][key]["latency_ms"],
                    "ms",
                )
                for before, after in changes
            ],
        )
    output_row(
        f"wide-unique take({count}) process peak RSS",
        [
            show_delta(
                summaries[before]["process_peak_rss_kib"],
                summaries[after]["process_peak_rss_kib"],
                "MiB",
                1024,
            )
            for before, after in changes
        ],
    )
for label, summaries in standalone.items():
    for metric, unit, scale in (("latency_ms", "ms", 1), ("rss_kib", "MiB", 1024)):
        output_row(
            f"{label}{' peak RSS' if metric == 'rss_kib' else ''}",
            [
                show_delta(
                    summaries[before][metric], summaries[after][metric], unit, scale
                )
                for before, after in changes
            ],
        )

print("\n## Exact reads\n")
print("Both experiments compared all scan and take values to the Arrow IPC inputs.")
print("The verify JSON records checked row counts, nulls, and value lengths.\n")
output_row(
    "Dataset",
    ("Scan rows per build", "Take rows per build", "Null", "Empty", "Short nonempty"),
)
output_row("---", ["---:"] * 5)
for kind in ("wide-unique", "wide-unique-8k", "wide-mixed"):
    a, b = (load(f"verify-{kind}-{build}.json") for build in ("exp-A", "exp-B"))
    assert a == b
    output_row(
        kind,
        [
            str(a[key])
            for key in (
                "scan_rows",
                "take_rows",
                "null_rows",
                "empty_rows",
                "short_nonempty_rows",
            )
        ],
    )

print("\n## Rust checks\n")
print(
    "- A and B ran `cargo test -q -p lance-encoding --profile release-with-debug`. "
    "[A test log](decode-followup/raw/test-exp-A.log) · "
    "[B test log](decode-followup/raw/test-exp-B.log)"
)
print("- Both builds ran `cargo fmt --all -- --check` with exit status 0.")
print(
    "- B ran `cargo clippy -p lance-encoding --tests --profile release-with-debug "
    "-- -D warnings` with exit status 0. "
    "[Clippy log](decode-followup/raw/clippy-exp-B.log)"
)

print("\n## Evidence wording for the page-splitting PR\n")
print(
    "The first call in each process used a newly opened dataset handle. "
    "Both builds used the same row selection and files from the same Arrow input."
)
print()
for count, summary in repeated.items():
    observations = []
    for key, label in (
        ("first", "the first call"),
        ("second", "the second call"),
        ("steady", "calls 6–20"),
    ):
        before = summary["base"][key]["latency_ms"]
        after = summary["final"][key]["latency_ms"]
        change = (after["median"] / before["median"] - 1) * 100
        observations.append(
            f"{before['median']:.2f} → {after['median']:.2f} ms "
            f"({change:+.2f}%) on {label}"
        )
    print(
        f"- `take({count})` median latency went from " + ", ".join(observations) + "."
    )

print(
    "\nThe 1,024 selected values contain 184.32 MB (175.78 MiB) of payload. "
    "The steady-state base-to-final gap is "
    + show_delta(
        repeated[1024]["base"]["steady"]["latency_ms"],
        repeated[1024]["final"]["steady"]["latency_ms"],
        "ms",
    )
    + "."
)
print("\n## Follow-up effects\n")
for before, after in (("final", "exp-A"), ("exp-A", "exp-B")):
    print(f"### {before} → {after}\n")
    print(
        "- Wide take medians, first call and calls 6–20. "
        + " ".join(
            f"For {count} rows, "
            + " and ".join(
                show_delta(
                    summary[before][key]["latency_ms"],
                    summary[after][key]["latency_ms"],
                    "ms",
                )
                for key in ("first", "steady")
            )
            + "."
            for count, summary in repeated.items()
        )
    )
    for label in ("wide-unique-8k scan", "wide-unique scan"):
        summary = standalone[label]
        latency = show_delta(
            summary[before]["latency_ms"], summary[after]["latency_ms"], "ms"
        )
        rss = show_delta(
            summary[before]["rss_kib"], summary[after]["rss_kib"], "MiB", 1024
        )
        print(f"- {label} changed by {latency} in median time and {rss} in peak RSS.")
    print()

rss_8k = standalone["wide-unique-8k scan"]
print(
    "The original 8k scan peak RSS increase was +25.86%, with a +10% criterion. "
    "In the new run, the baseline-to-final change was "
    + show_delta(rss_8k["base"]["rss_kib"], rss_8k["final"]["rss_kib"], "MiB", 1024)
    + ". The baseline-to-A change was "
    + show_delta(rss_8k["base"]["rss_kib"], rss_8k["exp-A"]["rss_kib"], "MiB", 1024)
    + " and the baseline-to-B change was "
    + show_delta(rss_8k["base"]["rss_kib"], rss_8k["exp-B"]["rss_kib"], "MiB", 1024)
    + ". [Original RSS criterion and results](summary.md)"
)
