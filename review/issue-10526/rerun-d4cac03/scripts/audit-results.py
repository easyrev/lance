"""Independently verify classifications against the raw measurements."""
import json
import re
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from statistics import median

root = Path(sys.argv[1])
groups = {}
for path in sorted((root / "raw/p1").glob("*.jsonl")):
    name, operation, cohort, trial, build = path.stem.rsplit("-", 4)
    assert cohort in {"primary", "repeat"} and build in {"base", "head"}, path
    records = [json.loads(line, parse_float=Decimal) for line in path.read_text().splitlines()]
    if operation == "scan":
        assert len(records) == 1
        first = records[0]
        metrics = {
            "耗时 ms": first["wall_seconds"] * 1000,
            "峰值 RSS MiB": Decimal(first["process_peak_rss_kib"]) / 1024,
        }
    else:
        assert len(records) == 20
        first, second = records[:2]
        metrics = {
            "首次 ms": first["take_ms"],
            "第二次 ms": second["take_ms"],
            "第 6–20 次 ms": median(r["take_ms"] for r in records[5:]),
            "首次峰值 RSS MiB": Decimal(first["process_peak_rss_kib"]) / 1024,
            "进程峰值 RSS MiB": Decimal(records[-1]["process_peak_rss_kib"]) / 1024,
        }
    for metric, number in metrics.items():
        group = groups.setdefault((name, operation, metric, build, cohort), {})
        assert int(trial) not in group
        group[int(trial)] = number

totals = Counter()
rows = 0
for line in (root / "reports/p1-summary.md").read_text().splitlines():
    if "base → head" not in line:
        continue
    name, op, n, metric, _, left, right, delta, percent, aa, verdict = (
        field.strip() for field in line.strip("|").split("|")
    )
    expected_n = 7 if op == "scan" else 5
    assert int(n) == expected_n
    samples = []
    for build in ("base", "head"):
        for cohort in ("primary", "repeat"):
            group = groups.pop((name, op, metric, build, cohort))
            assert set(group) == set(range(1, expected_n + 1))
            samples.append(list(group.values()))
    base, base_repeat, head, head_repeat = samples
    centers = [median(s) for s in samples]
    expected_delta = centers[2] - centers[0]
    threshold = 2 * max(abs(centers[1] - centers[0]), abs(centers[3] - centers[2]))
    separated = max(base) < min(head) or max(head) < min(base)
    expected = "在噪声内"
    if separated and abs(expected_delta) > threshold:
        expected = "收益" if expected_delta < 0 else "回归"
    assert verdict == expected, (name, op, metric, verdict, expected)
    assert abs(Decimal(delta) - expected_delta) <= Decimal("0.005")
    assert abs(Decimal(percent.rstrip("%")) - expected_delta / centers[0] * 100) <= Decimal("0.005")
    assert abs(Decimal(aa) - threshold) <= Decimal("0.005")
    for cell, center, values in ((left, centers[0], base), (right, centers[2], head)):
        fields = re.fullmatch(r"(\d+\.\d+) \[(\d+\.\d+)–(\d+\.\d+)\]", cell).groups()
        for actual, value in zip(fields, (center, min(values), max(values)), strict=True):
            assert abs(Decimal(actual) - value) <= Decimal("0.005")
    totals[verdict] += 1
    rows += 1
assert not groups and rows == 96
print(f"Verified {rows} rows from raw timing data with decimal arithmetic: {dict(totals)}")
