import csv
import json
import statistics
import sys
from pathlib import Path

raw = Path(sys.argv[1])
variants = ("base", "pure", "var")
rss = {}
for variant in variants:
    runs = [json.loads((raw / f"checkpoints-{i}-{variant}.json").read_text()) for i in range(1, 6)]
    rss[variant] = {}
    for point in ("import_peak_rss_kib", "open_peak_rss_kib", "process_peak_rss_kib"):
        values = [run[point] / 1024 for run in runs]
        rss[variant][point] = (statistics.median(values), min(values), max(values))

print("# 单页 RSS 归因")
print()
print("单次 take(128)，每构建 5 个独立进程，按 base、pure-B、pure-B-var 交替。数值是进程峰值 RSS 的中位数 [min–max]，单位 MiB。")
print()
print("| 记录点 | main | pure-B | pure-B-var | pure-B − main | pure-B-var − main |")
print("|---|---:|---:|---:|---:|---:|")
for title, point in (
    ("import lance 后", "import_peak_rss_kib"),
    ("dataset open 后", "open_peak_rss_kib"),
    ("首次调用后", "process_peak_rss_kib"),
):
    values = [rss[variant][point] for variant in variants]
    cells = [f"{m:.2f} [{lo:.2f}–{hi:.2f}]" for m, lo, hi in values]
    diff = [f"{values[i][0] - values[0][0]:+.2f}" for i in (1, 2)]
    print("| " + " | ".join((title, *cells, *diff)) + " |")

print()
print("## perf uprobe")
print()
print("快路径探针是优化后独立存在的 `VariableFullZipDecodeTask::decode_variable_into` 方法入口。组合层的 `decode_variable` 内联，计数单位是进入该方法的页任务。main 的快路径事件不适用。文件偏移使用 ELF LOAD 段从虚拟地址换算。")
print()
print("| 构建 | 输入和操作 | 快路径页任务 | concat_decoded_arrays |")
print("|---|---|---:|---:|")
for variant in variants:
    operations = ("take128", "scan") if variant == "base" else ("take128", "scan", "multipage-control")
    for operation in operations:
        with (raw / f"probe-{variant}-{operation}.csv").open() as stream:
            rows = csv.reader(line for line in stream if line.strip() and not line.startswith("#"))
            events = {row[2].rsplit("_", 1)[1]: int(row[0]) for row in rows}
        fast = events.get("fast", "–")
        print(f"| {variant} | {operation} | {fast} | {events['concat']} |")

print()
print("## 扩展大小")
print()
print("| 构建 | 文件字节 | .text | .rodata | .data | .bss |")
print("|---|---:|---:|---:|---:|---:|")
for variant in variants:
    sections = {}
    for line in (raw / f"size-A-{variant}.txt").read_text().splitlines():
        parts = line.split()
        if parts and parts[0] in (".text", ".rodata", ".data", ".bss"):
            sections[parts[0]] = int(parts[1])
    size = int((raw / f"file-size-{variant}.txt").read_text().split()[0])
    numbers = [size] + [sections[name] for name in (".text", ".rodata", ".data", ".bss")]
    print(f"| {variant} | " + " | ".join(f"{val:,}" for val in numbers) + " |")

print()
print("单页 scan 和 take 的快路径计数均为零，多页 take 正对照各记录 85 次。RSS 增量在 import 后已存在，归为加载这两个候选二进制时的固定开销。section 大小单独记录，未测量各 section 的驻留页数。")
