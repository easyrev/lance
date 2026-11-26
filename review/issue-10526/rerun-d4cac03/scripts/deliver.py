"""Render the rerun reports from the archived comparison and new raw samples."""
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])
raw = root / "raw"
reports = root / "reports"


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(map(str, row)) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def output(name, parts):
    (reports / f"{name}.md").write_text("\n".join(parts))


def read_summary(path, comparison):
    result = {}
    for line in path.read_text().splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 11 and cells[4] == comparison:
            key = (cells[0], cells[1], cells[3])
            assert key not in result, key
            result[key] = cells
    assert len(result) == 96, path
    return result


old = read_summary(root / "reused" / "old-summary.md", "base → pure")
new = read_summary(reports / "p1-summary.md", "base → head")
assert old.keys() == new.keys()
priority = {
    "utf8-zstd-25k": [
        ("repeat128", "首次 ms"),
        ("repeat1024", "第 6–20 次 ms"),
        ("repeat1024", "进程峰值 RSS MiB"),
        ("scan", "耗时 ms"),
        ("scan", "峰值 RSS MiB"),
    ],
    "utf8-zstd-8k": [("scan", "峰值 RSS MiB")],
    "binary-zstd-varlen": [
        ("repeat128", "第 6–20 次 ms"),
        ("repeat1024", "进程峰值 RSS MiB"),
        ("scan", "峰值 RSS MiB"),
    ],
    "binary-random-varlen": [("repeat1024", "首次 ms"), ("repeat1024", "进程峰值 RSS MiB")],
    "binary-zstd-medium": [("repeat1024", "首次 ms")],
    "mixed": [("scan", "耗时 ms"), ("scan", "峰值 RSS MiB")],
}
priority_rows = []
for name, metrics in priority.items():
    for operation, metric in metrics:
        key = (name, operation, metric)
        current, prior = new[key], old[key]
        priority_rows.append((*key, *current[5:7], current[8], current[10],
                              *prior[5:7], prior[8], prior[10]))
output("pr-rows", [
    "# PR 正文用数据\n",
    "数值为正式组中位数 [min–max]。旧轮来自 `ed4c87940` 的 `matched-env/summary.md`。\n",
    table(("数据集", "操作", "指标", "本轮 base", "本轮 head", "本轮变化", "本轮判定",
           "旧 base", "旧 pure", "旧变化", "旧判定"), priority_rows),
])

transitions = Counter((old[key][-1], new[key][-1]) for key in new)
lost = [key for key in new if old[key][-1] == "收益" and new[key][-1] != "收益"]
gained = [key for key in new if old[key][-1] == "在噪声内" and new[key][-1] != "在噪声内"]
controls = [key for key in new if key[0] in {"utf8-1page", "binary-medium-default"}
            and new[key][-1] != "在噪声内"]
fast = [
    "# Bridging 快路径对照\n",
    "逐行对应旧版 `ed4c87940` 的 base → pure 比较，共 96 项。\n",
    table(("旧判定", "本轮判定", "项数"), (pair + (count,) for pair, count in sorted(transitions.items()))),
]
for section, keys in [
    ("旧收益未保留", lost),
    ("旧表在噪声内且本轮超出噪声", gained),
    ("对照组超出噪声", controls),
    ("全部判定", list(new)),
]:
    fast.append(f"## {section}（{len(keys)} 项）\n")
    if keys:
        fast.append(table(("数据集", "操作", "指标", "旧变化", "旧判定", "本轮变化", "本轮判定"),
                          ((*key, old[key][8], old[key][-1], new[key][8], new[key][-1]) for key in keys)))
if lost:
    diagnostic = reports / "diagnostic.md"
    if diagnostic.exists():
        fast.append(diagnostic.read_text())
    else:
        fast.append("## 本地诊断\n\n待运行。")
else:
    fast.append("旧收益均保留。按交接单的触发条件，本轮无需临时诊断构建。")
output("fast-path", fast)
(reports / "diagnostic-cases.tsv").write_text("".join(
    f"{dataset}\t{op}\n" for dataset, op in dict.fromkeys(
        (key[0], key[1]) for key in (lost + controls if lost else [])
    )
))

print("transitions:", dict(transitions))
print("lost:", len(lost), "old-noise changes:", len(gained), "controls:", len(controls))

build_rows = []
for build in ("base", "head"):
    values = [int((raw / "imports" / f"{build}-{n}.txt").read_text()) / 1024 for n in range(1, 6)]
    sha = (raw / f"commit-{build}.txt").read_text().strip()
    extension = (raw / f"extension-{build}.sha256").read_text().split()[0]
    build_rows.append((build, f"`{sha}`", f"`{extension}`", ", ".join(f"{n:.3f}" for n in values),
                       f"{statistics.median(values):.3f} [{min(values):.3f}–{max(values):.3f}]"))
machine = (raw / "machine.txt").read_text()
initial_space = "\n".join((raw / "space.log").read_text().splitlines()[:4])
cleanup = (raw / "cleanup-old-target.txt").read_text() if (raw / "cleanup-old-target.txt").exists() else ""
output("environment", [
    "# 环境与导入 RSS\n",
    "经确认沿用当前实例。两个 detached worktree 各用独立 Cargo target 和独立虚拟环境。"
    "构建配置为 `release-with-debug`，测量设置 `LANCE_CPU_THREADS=64`。"
    "base 构建完成后将 Cargo 缓存移至 tmpfs，安装后的扩展路径及 SHA256 保持一致。"
    "两套扩展和原始输出位于实例的持久磁盘（根卷）。"
    "首次迁移在隔离的命令环境中找不到宿主机上的目标目录。随后在宿主机重试，"
    "并复核了迁移前后的扩展哈希。等待构建的测量任务也改在宿主机重启，当时尚未生成数据或采样。"
    "详见 [缓存迁移记录](raw/target-base-relocation.log)。\n",
    table(("构建", "提交", "扩展 SHA256", "5 个进程的峰值 RSS（MiB）", "中位数 [min–max]（MiB）"),
          build_rows),
    "两份 `pip freeze --all` 去掉各自的 pylance 条目后逐字节一致。"
    "解释器的实际路径、版本和 SHA256 一致。两个 native 扩展 SHA256 不同。"
    "详见 [freeze 与环境审计](raw/environment-match.txt) 和 [完整机器记录](raw/machine.txt)。\n",
    "## 构建前的宿主机空间\n\n```text\n" + initial_space + "\n```\n",
    "## CPU、内存、系统和工具链\n\n"
    "以下为预检命令环境快照。上表是实际执行构建的宿主机空间，"
    "后续宿主机快照见 [machine-host.txt](raw/machine-host.txt)。\n\n```text\n"
    + machine.rstrip() + "\n```\n",
    "## 磁盘整理\n\n" + "\n".join(f"- `{line.removeprefix('Deleted: ')}`"
                                             for line in cleanup.splitlines() if line.startswith("Deleted: ")),
])

counts = {}
for line in (raw / "data.log").read_text().splitlines():
    if line.startswith("{"):
        entry = json.loads(line)
        counts[entry["dataset"]] = entry["encodings"]
dataset_rows = []
exact = []
descriptions = {
    "utf8-1page": "180,000 字节 LargeUtf8，4096 词表",
    "utf8-zstd-25k": "180,000 字节 LargeUtf8，4096 词表",
    "utf8-zstd-8k": "180,000 字节 LargeUtf8，4096 词表",
    "binary-zstd-varlen": "64–512 KiB LargeBinary，4096 词表，1% null、1% 空值",
    "binary-random-varlen": "64–512 KiB LargeBinary，高熵随机字节，1% null、1% 空值",
    "binary-zstd-medium": "8–32 KiB LargeBinary，4096 词表，1% null、1% 空值",
    "binary-medium-default": "8–32 KiB LargeBinary，4096 词表，1% null、1% 空值",
    "mixed": "LargeBinary，前半 8–16 KiB、后半 64–128 KiB，1% null、1% 空值",
}
for name, encodings in counts.items():
    write = json.loads((raw / "data" / f"write-{name}.json").read_text())
    info = json.loads((raw / "data" / f"pages-{name}.json").read_text())
    mode = "RecordBatchReader" if write["stream"] else "RecordBatch"
    compression = "compression=zstd" if write["zstd_metadata"] else "默认压缩"
    codec = "、".join(f"{key.replace('General/CompressionAlgorithm', '')} × {count}"
                     for key, count in sorted(encodings.items()))
    dataset_rows.append((name, descriptions[name], write["rows"], mode, len(write["batch_bytes"]),
                         compression, info["pages"], codec, info["file_bytes"], f"`{info['sha256']}`"))
    for build in ("base", "head"):
        read = json.loads((raw / "exact" / f"{name}-{build}.json").read_text())
        assert read["matched"] and read["scan_rows"] == read["take_rows"] == write["rows"]
        assert read["take_calls"] == 1
        exact.append((name, build, read["scan_rows"], read["take_rows"], "逐行一致"))
assert counts.keys() == descriptions.keys()
output("datasets", [
    "# 数据集与精确性门禁\n",
    "八个数据集均由 base 写出，使用格式 `2.2`、seed 10526。流式写入以约 32 MB 分批。"
    "逐页编码原文、输入及文件哈希在 [raw/data](raw/data)。\n",
    table(("数据集", "内容", "行数", "写入", "批数", "压缩设置", "页数", "编码", "文件字节数", "SHA256"), dataset_rows),
    "## 精确性门禁\n\n两个构建分别执行一次全扫描和一次全量随机排列 take。"
    "使用 Arrow 逐位置比较行值和 null。take 返回后分块比对以控制额外内存。\n",
    table(("数据集", "构建", "扫描行数", "随机排列 take 行数", "结果"), exact),
])
