import collections
import json
import re
import sys
from pathlib import Path


def value_encoding(page):
    layout = re.search(r"layout: Some\(\s*(\w+)\(", page)
    if layout is None:
        return "Unknown"
    name = layout[1].removesuffix("Layout")
    if name != "FullZip":
        return name
    value = re.search(r"value_compression: Some\(\s*CompressiveEncoding \{\s*compression: Some\(\s*(\w+)", page)
    if value is None:
        return name
    if value[1] == "General":
        codec = re.search(r"scheme: (\w+)", page)
        return f"{name}/General/{codec[1] if codec else 'Unknown'}"
    return f"{name}/{value[1]}"


raw = Path(sys.argv[1])
phase = sys.argv[2]
names = (
    ["utf8-1page", "utf8-zstd-25k", "utf8-zstd-8k", "binary-zstd-varlen",
     "binary-random-varlen", "binary-zstd-medium", "mixed"]
    if phase == "phase1" else
    [f"{name}-{build}" for name in (
        "wide-unique", "wide-unique-8k", "wide-low-card", "wide-repeated",
        "wide-template", "wide-clustered", "wide-mixed", "wide-constant", "narrow"
    ) for build in ("base", "final")]
)
prefix = "" if phase == "phase1" else "phase2-"
print("| 数据集 | 写入 | 页数 | 页编码及数量 | 文件字节数 | `.lance` SHA256 |")
print("|---|---|---:|---|---:|---|")
for name in names:
    path = raw / f"{prefix}pages-{name}.json"
    if not path.exists():
        print(f"| {name} | 未测量 | | | | |")
        continue
    info = json.loads(path.read_text())
    pages = json.loads((raw / f"{prefix}pages-{name}-detail.json").read_text())
    assert len(pages) == info["pages"]
    encodings = collections.Counter(map(value_encoding, pages))
    codecs = "、".join(f"{kind} × {count}" for kind, count in encodings.items())
    if phase == "phase1":
        write = json.loads((raw / f"write-{name}.json").read_text())
        batches = write["batch_bytes"]
        mode = "RecordBatchReader" if write["stream"] else "RecordBatch"
        compressor = "，compression=zstd" if write["zstd_metadata"] else "，默认压缩配置"
        how = f"{write['rows']:,} 行，{mode}，{len(batches)} batch{compressor}"
    else:
        how = "IPC 单批次，单 writer，默认压缩配置"
    print(f"| {name} | {how} | {len(pages)} | {codecs} | {info['file_bytes']:,} | `{info['sha256']}` |")
