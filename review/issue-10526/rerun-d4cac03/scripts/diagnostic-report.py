"""Count completed bridging and concat attempts by composite task size."""
import re
import sys
from collections import Counter
from pathlib import Path

disk = Path(sys.argv[1])
report = disk / "reports"
raw = disk / "raw/diagnostic"
cases = [tuple(line.split("\t")) for line in (report / "diagnostic-cases.tsv").read_text().splitlines()]
header = r"^PR1_BRIDGE outcome (bridge|concat|error) pages=(\d+)"
reason = r"^PR1_BRIDGE reason (\S+ \S+)"
print("## 本地诊断\n")
print("使用固定 head 的独立工作树加临时日志。下表为 composite task 次数。"
      "扫描运行一次，take 用同一句柄运行 20 次。详细日志和临时补丁见 [raw/diagnostic](raw/diagnostic)。\n")
print("| 数据集 | 操作 | 多页 bridging 成功 | 多页 concat | 单页 concat | bridging 错误 |")
print("|---|---|---:|---:|---:|---:|")
reasons = {}
missed = []
control_counts = []
for dataset, op in cases:
    lines = (raw / f"{dataset}-{op}.log").read_text().splitlines()
    outcomes = Counter()
    reasons[dataset, op] = Counter()
    for line in lines:
        if match := re.match(header, line):
            kind, pages = match.groups()
            outcomes[kind, int(pages) > 1] += 1
        if match := re.match(reason, line):
            reasons[dataset, op][match[1]] += 1
    assert outcomes, (dataset, op, "no composite task markers")
    assert not outcomes["bridge", False]
    if dataset in {"utf8-1page", "binary-medium-default"}:
        control_counts.append((dataset, op, outcomes["bridge", True]))
    elif outcomes["bridge", True] == 0:
        missed.append((dataset, op))
    print(f"| {dataset} | {op} | {outcomes['bridge', True]} | {outcomes['concat', True]} | "
          f"{outcomes['concat', False]} | {outcomes['error', True]} |")
print()
if not missed:
    print("四项旧收益未保留的对应诊断用例均观察到多页 bridging 成功，排除这些用例整体静默回退。")
else:
    print("至少一个诊断用例的多页 bridging 成功次数为 0，路径分布见上表。")
for dataset, op, count in control_counts:
    print(f"对照组 `{dataset}` 的 `{op}` 观察到 {count} 次多页 bridging 成功。")
print("\n### 返回 None 的位置\n")
print("位置为原始 `d4cac03` 下的源代码行。同一 fallback 可同时计入页级与 composite 上层检查。\n")
print("| 数据集 | 操作 | 位置和检查 | 次数 |")
print("|---|---|---|---:|")
for (dataset, op), counts in reasons.items():
    for label, count in sorted(counts.items()):
        print(f"| {dataset} | {op} | `{label}` | {count} |")
