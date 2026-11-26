from pathlib import Path
import json
import statistics
import sys

raw = Path(sys.argv[1])
required = [
    ("wide-unique-8k", "scan", "+25.86%"),
    ("wide-repeated", "scan", "+19.54%"),
    ("wide-repeated", "take", "+16.30%"),
    ("wide-clustered", "scan", "+11.36%"),
    ("wide-clustered", "take", "+17.50%"),
]
print("| 数据集 | 操作 | 上轮 base → final | 本轮 base → final | 本轮 base → final+B |")
print("|---|---|---:|---:|---:|")
for name, kind, historical in required:
    readings = {}
    for variant in ("base", "final", "final-b"):
        paths = [raw / f"phase2-{kind}-{name}-{i}-{variant}.jsonl" for i in (1, 2, 3)]
        if all(p.is_file() for p in paths):
            readings[variant] = statistics.median(json.loads(p.read_text())["process_peak_rss_kib"] for p in paths)
    out = []
    for variant in ("final", "final-b"):
        if "base" not in readings or variant not in readings:
            out.append("未测量")
        else:
            pct = (readings[variant] / readings["base"] - 1) * 100
            status = "达标" if pct <= 10 else "超标"
            out.append(f"{pct:+.2f}% ({status})")
    print(f"| {name} | {kind} | {historical} | {out[0]} | {out[1]} |")
