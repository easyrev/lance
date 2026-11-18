#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from statistics import median


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def time_field(path: Path, label: str) -> str:
    for line in path.read_text().splitlines():
        if line.lstrip().startswith(label):
            return line.rsplit(": ", 1)[1]
    raise ValueError(f"Missing {label!r} in {path}")


def writer_stats(raw: Path, writers: int, threads: int, variant: str) -> tuple:
    runs = []
    peaks = []
    for trial in range(1, 4):
        name = f"write-{writers}-{threads}-{trial}-{variant}"
        runs.append(read_json(raw / f"{name}.json"))
        peaks.append(
            int(time_field(raw / f"{name}.time", "Maximum resident set size (kbytes)"))
        )
    pre_write = [run["pre_write_rss_kib"] for run in runs]
    return (
        median(run["write_wall_seconds"] for run in runs),
        median(peaks),
        median(pre_write),
        median(peak - before for peak, before in zip(peaks, pre_write)),
    )


def main(raw: Path) -> None:
    print("### Wall time")
    print()
    print("| Step | Elapsed (m:ss) |")
    print("| --- | ---: |")
    for label, name in (
        ("Baseline build and install", "build-baseline"),
        ("Fix build and install", "build-fix"),
        ("Arrow IPC generation", "generate"),
    ):
        path = raw / f"{name}.time"
        if path.exists() and path.stat().st_size:
            elapsed = time_field(path, "Elapsed (wall clock)")
            print(f"| {label} | {elapsed} |")
    for label, start, end in (
        ("Write matrix", "write-matrix-start", "measure-end"),
        ("End to end", "measurement-start", "measure-exit"),
    ):
        start_path = raw / f"{start}.epoch"
        end_path = raw / f"{end}.epoch"
        if start_path.exists() and end_path.exists():
            elapsed = float(end_path.read_text()) - float(start_path.read_text())
            minutes, seconds = divmod(elapsed, 60)
            print(f"| {label} | {int(minutes)}:{seconds:05.2f} |")
    print()

    print("### Table A. Files")
    print()
    print(
        "| Input | Baseline file B | Pages | Max page B |"
        " Fix file B | Pages | Max page B |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for dataset in ("wide-unique", "wide-repeated", "narrow"):
        paths = [
            raw / f"file-{dataset}-{variant}.json" for variant in ("baseline", "fix")
        ]
        if not all(path.stat().st_size if path.exists() else 0 for path in paths):
            continue
        results = [read_json(path) for path in paths]
        cells = (
            f"{result[key]:,}"
            for result in results
            for key in ("file_bytes", "pages", "max_page_bytes")
        )
        print(f"| {dataset} | " + " | ".join(cells) + " |")

    if not (raw / "measure-end.epoch").exists():
        return

    print()
    print("### Table B. Median of three writes")
    print()
    print(
        "| Writers | CPU threads | Build | Write s | Peak RSS KiB |"
        " Pre-write RSS KiB | Peak minus pre-write KiB |"
    )
    print("| ---: | ---: | --- | ---: | ---: | ---: | ---: |")
    checks = []
    for writers in (1, 8):
        for threads in (8, 16):
            baseline = writer_stats(raw, writers, threads, "baseline")
            fix = writer_stats(raw, writers, threads, "fix")
            for variant, stats in (("baseline", baseline), ("fix", fix)):
                wall, peak, pre_write, increment = stats
                print(
                    f"| {writers} | {threads} | {variant} | {wall:.3f}"
                    f" | {peak:,} | {pre_write:,} | {increment:,} |"
                )
            rss_ratio = fix[1] / baseline[1]
            checks.append(
                f"- {writers} writer(s), {threads} CPU threads, peak RSS ratio "
                f"{rss_ratio:.4f}. {'Pass' if rss_ratio <= 1.10 else 'Miss'}."
            )
            if (writers, threads) == (8, 8):
                wall_ratio = fix[0] / baseline[0]
                checks.append(
                    f"- 8 writers, 8 CPU threads, wall-time ratio {wall_ratio:.4f}. "
                    f"{'Pass' if wall_ratio <= 1.05 else 'Miss'}."
                )
    print()
    print("\n".join(checks))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
