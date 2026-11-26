import argparse
import json
import statistics
from pathlib import Path


def metrics(path, phase):
    values = [json.loads(line) for line in path.read_text().splitlines()]
    first, last = values[0], values[-1]
    if len(values) == 1:
        return {"wall ms": first["wall_seconds"] * 1000, "peak RSS MiB": first["process_peak_rss_kib"] / 1024}
    assert len(values) == 20
    result = {
        "first ms": first["take_ms"],
        "second ms": values[1]["take_ms"],
        "6–20 median ms": statistics.median(v["take_ms"] for v in values[5:]),
        "first peak RSS MiB": first["process_peak_rss_kib"] / 1024,
        "process peak RSS MiB": last["process_peak_rss_kib"] / 1024,
    }

    if phase == "phase2":
        result["second peak RSS MiB"] = values[1]["process_peak_rss_kib"] / 1024
        result["6–20 median peak RSS MiB"] = statistics.median(v["process_peak_rss_kib"] for v in values[5:]) / 1024
    return result


def series(raw, phase, dataset, operation, variant, limit):
    paths = [raw / f"{phase}-{operation}-{dataset}-{trial}-{variant}.jsonl" for trial in range(1, limit + 1)]
    if not all(p.exists() and p.stat().st_size for p in paths):
        return None
    runs = [metrics(path, phase) for path in paths]
    return {metric: (statistics.median(trials), min(trials), max(trials))
            for metric, trials in ((k, [run[k] for run in runs]) for k in runs[0])}


def delta(reference, candidate):
    return (candidate[0] / reference[0] - 1) * 100


def verdict(reference, candidate):
    change = delta(reference, candidate)
    if change > 0 and candidate[1] > reference[2]:
        return "回归"
    if change > 3:
        return "区间相交，中位数增加超过 3%"
    return ""


def comparisons(raw, phase, dataset, operation, variants, count):
    samples = {v: series(raw, phase, dataset, operation, v, count) for v in variants}
    if not all(samples.values()):
        return
    for metric in samples[variants[0]]:
        yield metric, [samples[v][metric] for v in variants]


def report(raw, phase, variants):
    names = set()
    for path in raw.glob(f"{phase}-*-3-{variants[0]}.jsonl"):
        op, name = path.stem.removeprefix(f"{phase}-").removesuffix(f"-3-{variants[0]}").split("-", 1)
        names.add((name, op))
    pairs = [(0, 1), (0, 2), (1, 2)] if len(variants) == 3 else [(0, 1)]
    header = ["数据集", "操作", "进程数", "指标", *variants, *(f"{variants[a]} → {variants[b]}" for a, b in pairs)]
    print("| " + " | ".join(header) + " |")
    print("|" + "|".join("---" for _ in header) + "|")
    for name, op in sorted(names):
        for n in (3, 5):
            for metric, values in comparisons(raw, phase, name, op, variants, n):
                cells = [name, op, str(n), metric]
                cells += [f"{m:.2f} [{lo:.2f}–{hi:.2f}]" for m, lo, hi in values]
                for a, b in pairs:
                    outcome = verdict(values[a], values[b])
                    cells.append(f"{delta(values[a], values[b]):+.2f}%" + (f"，{outcome}" if outcome else ""))
                print("| " + " | ".join(cells) + " |")


parser = argparse.ArgumentParser()
parser.add_argument("command", choices=("retry", "stop", "report"))
parser.add_argument("raw", type=Path)
parser.add_argument("operation", nargs="?")
parser.add_argument("dataset", nargs="?")
parser.add_argument("--phase", default="phase1")
parser.add_argument("--variants", default="base,pure,var")
args = parser.parse_args()
variants = args.variants.split(",")
if args.command == "report":
    report(args.raw, args.phase, variants)
    raise SystemExit(0)
if args.command == "retry":
    count = 3
    pairs = [(0, 1), (0, 2), (1, 2)]
    condition = "区间相交，中位数增加超过 3%"
else:
    count = 5 if series(args.raw, args.phase, args.dataset, args.operation, variants[0], 5) else 3
    pairs = [(0, 1)]
    condition = "回归"
matched = False
for metric, values in comparisons(args.raw, args.phase, args.dataset, args.operation, variants, count):
    for a, b in pairs:
        if verdict(values[a], values[b]) == condition:
            print(f"{args.dataset} {args.operation} {metric} {variants[a]} → {variants[b]} n={count} {delta(values[a], values[b]):+.2f}% {condition}")
            matched = True
raise SystemExit(0 if matched else 1)
