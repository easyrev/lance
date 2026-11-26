import json
import statistics
import sys
from collections import Counter
from pathlib import Path

disk = Path(sys.argv[1])
raw = disk / "raw"
phase = sys.argv[2]
out = disk / "reports"
out.mkdir(exist_ok=True)
p1_rows = {
    "utf8-1page": 25000,
    "utf8-zstd-25k": 25000,
    "utf8-zstd-8k": 8000,
    "binary-zstd-varlen": 12000,
    "binary-random-varlen": 12000,
    "binary-zstd-medium": 99650,
    "binary-medium-default": 99650,
    "mixed": 16000,
}
p2_rows = {
    "wide-unique": 25000,
    "wide-unique-8k": 8000,
    "wide-low-card": 25000,
    "wide-repeated": 8000,
    "wide-template": 25000,
    "wide-clustered": 25000,
    "wide-mixed": 25000,
    "wide-constant": 25000,
    "narrow": 10000000,
}


def stats(values):
    return statistics.median(values), min(values), max(values)


def display(values):
    mean, low, high = values
    return f"{mean:.2f} [{low:.2f}–{high:.2f}]"


def table(stream, headers, rows):
    print("| " + " | ".join(headers) + " |", file=stream)
    print("|" + "|".join("---" for _ in headers) + "|", file=stream)
    for row in rows:
        print("| " + " | ".join(str(value) for value in row) + " |", file=stream)


def load_metrics(path, op, rows, expected_indices):
    records = [json.loads(line) for line in path.read_text().splitlines()]
    if op.startswith("repeat"):
        assert len(records) == 20, path
        first, second, *remaining = records
        steady = remaining[3:]
        count = int(op.removeprefix("repeat"))
        expected_indices = check_take(records, rows, count, expected_indices)
        measurements = {
            "首次 ms": first["take_ms"],
            "第二次 ms": second["take_ms"],
            "第 6–20 次 ms": statistics.median(r["take_ms"] for r in steady),
            "首次峰值 RSS MiB": first["process_peak_rss_kib"] / 1024,
            "进程峰值 RSS MiB": records[-1]["process_peak_rss_kib"] / 1024,
        }
        if phase == "p2":
            measurements["第二次峰值 RSS MiB"] = second["process_peak_rss_kib"] / 1024
            measurements["第 6–20 次峰值 RSS MiB"] = statistics.median(r["process_peak_rss_kib"] / 1024 for r in steady)
        return measurements, expected_indices
    assert len(records) == 1, path
    [first] = records
    if op == "scan":
        assert first["rows"] == rows, path
    else:
        expected_indices = check_take(records, rows, 128, expected_indices)
    return {
        "耗时 ms": first["wall_seconds"] * 1000,
        "峰值 RSS MiB": first["process_peak_rss_kib"] / 1024,
    }, expected_indices


def check_take(records, rows, count, expected):
    for record in records:
        indices = record["indices"]
        assert record["rows"] == len(indices) == count
        assert indices == sorted(set(indices)) and min(indices) >= 0 and max(indices) < rows
        if expected is None:
            expected = indices
        assert indices == expected
    return expected


if phase == "environment":
    with (out / "environment.md").open("w") as report:
        print("# 匹配环境与导入 RSS\n", file=report)
        rows = []
        for name in ("base", "pure", "final", "final-b"):
            values = [int((raw / "imports" / f"{name}-{i}.txt").read_text()) / 1024 for i in range(1, 6)]
            commit = (raw / f"commit-{name}.txt").read_text().strip()
            extension = (raw / f"extension-{name}.sha256").read_text().split()[0]
            rows.append((name, f"`{commit}`", f"`{extension}`", display(stats(values))))
        table(report, ["构建", "提交", "现有扩展 SHA256", "import 后峰值 RSS MiB，N=5"], rows)
        print("\n四套环境的 pip freeze、解释器、Lance Python 源文件与依赖的运行库一致。虚拟环境各自的绝对路径反映在命令启动器及其 13 份 wheel RECORD 校验记录中。核验了启动器路径归一化后的内容和 RECORD 中的真实哈希。", file=report)
    raise SystemExit(0)

if phase == "p1":
    data = p1_rows
    builds = ("base", "head")
    cases = [(name, rows, op) for name, rows in data.items() for op in ("scan", "repeat128", "repeat1024")]
else:
    assert phase == "p2"
    data = p2_rows
    builds = ("base", "final", "final-b")
    cases = [(name, rows, op) for name, rows in data.items() for op in ("scan", "take")]
    cases.extend(("wide-unique", p2_rows["wide-unique"], op) for op in ("repeat128", "repeat1024"))

primary_rows = []
noise_rows = []
decisions = []
totals = Counter()
observed = set()
for dataset, rows, op in cases:
    n = 7 if op == "scan" else 5
    case = {}
    expected_indices = None
    for build in builds:
        for cohort in ("primary", "repeat"):
            samples = []
            for i in range(1, n + 1):
                path = raw / phase / f"{dataset}-{op}-{cohort}-{i}-{build}.jsonl"
                measures, expected_indices = load_metrics(path, op, rows, expected_indices)
                samples.append(measures)
                observed.add(path)
            outcome = {metric: stats([sample[metric] for sample in samples]) for metric in samples[0]}
            case[build, cohort] = outcome
    for metric in case[builds[0], "primary"]:
        change = {}
        for build in builds:
            first = case[build, "primary"][metric]
            second = case[build, "repeat"][metric]
            delta = second[0] - first[0]
            change[build] = delta
            noise_rows.append((dataset, op, n, metric, build, display(first), display(second), f"{delta:+.2f}", f"{delta / first[0] * 100:+.2f}%"))
        for i, reference in enumerate(builds):
            for candidate in builds[i+1:]:
                first = case[reference, "primary"][metric]
                second = case[candidate, "primary"][metric]
                delta = second[0] - first[0]
                noise = max(abs(change[reference]), abs(change[candidate]))
                threshold = 2 * noise
                separated = first[2] < second[1] or second[2] < first[1]
                verdict = "在噪声内"
                if separated and abs(delta) > threshold:
                    verdict = "回归" if delta > 0 else "收益"
                comparison = f"{reference} → {candidate}"
                result = (
                    dataset, op, n, metric, comparison, display(first), display(second),
                    f"{delta:+.2f}", f"{delta / first[0] * 100:+.2f}%", f"{threshold:.2f}", verdict,
                )
                primary_rows.append(result)
                totals[(comparison, verdict)] += 1
                if verdict != "在噪声内":
                    decisions.append(result)
assert observed == set((raw / phase).glob("*.jsonl"))
headers = ["数据集", "操作", "每组 N", "指标", "比较", "参考 [min–max]", "候选 [min–max]", "差值", "变化", "2× A/A", "判定"]
with (out / f"{phase}-summary.md").open("w") as summary:
    print("# 正式比较\n", file=summary)
    print("耗时与峰值 RSS 分别以 ms 与 MiB 计。每个用例先完成正式组，再完成重复组，组内轮转所有构建。2× A/A 是双方同构建两组的中位数绝对差取较大值后翻倍。判定使用未舍入数值。\n", file=summary)
    table(summary, headers, primary_rows)
with (out / f"{phase}-aa.md").open("w") as aa:
    print("# 同构建 A/A\n", file=aa)
    table(aa, ["数据集", "操作", "每组 N", "指标", "构建", "正式 [min–max]", "重复 [min–max]", "重复 − 正式", "变化"], noise_rows)
with (out / f"{phase}-classified.md").open("w") as result:
    print("# 超出噪声的指标\n", file=result)
    table(result, headers, decisions)
    print("\n## 按比较计数\n", file=result)
    table(result, ["比较", "收益", "回归", "在噪声内"], [
        (pair, *(totals[pair, label] for label in ("收益", "回归", "在噪声内")))
        for pair in dict.fromkeys(pair for pair, _ in totals)
    ])
print(f"{phase}: {len(cases)} cases, {len(observed)} timed processes, {len(primary_rows)} comparisons")
for (comparison, verdict), count in sorted(totals.items()):
    print(comparison, verdict, count)
