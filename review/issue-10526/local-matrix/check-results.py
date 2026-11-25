import csv
import statistics
import sys
from collections import defaultdict

with open(sys.argv[1]) as file:
    results = defaultdict(list)
    for row in csv.DictReader(file, delimiter="\t"):
        results[row["variant"], row["workload"]].append(row)

for (variant, workload), rows in results.items():
    if variant in ("baseline", "fix"):
        continue
    comparison = results["fix", workload]
    bytes_ratio = int(rows[0]["file_bytes"]) / int(comparison[0]["file_bytes"])
    read_ratio = statistics.median(float(r["read_ms"]) for r in rows) / statistics.median(
        float(r["read_ms"]) for r in comparison
    )
    is_p2 = variant.startswith("p2")
    should_split = workload in ("unique", "consecutive", "template") or (
        is_p2 and workload in ("mostly-wide", "mostly-short")
    )
    pages = int(rows[0]["pages"])
    peak_raw = int(rows[0]["max_raw_bytes"])
    assert (pages > 1) == should_split, (variant, workload, pages)
    if should_split:
        assert peak_raw <= 32 * 1024**2 + 180_000, (variant, workload, peak_raw)
    if workload in ("constant", "dirty-null"):
        assert "ConstantLayout" in rows[0]["layouts"], (variant, workload)
    if workload == "consecutive":
        assert "MiniBlockLayout" in rows[0]["layouts"], (variant, workload)
        assert "dictionary: Some" in rows[0]["layouts"], (variant, workload)
    verdict = "PASS" if bytes_ratio <= 1.02 and read_ratio <= 1.10 else "CHECK"
    print(f"{variant:15} {workload:12} n={len(rows)} pages={pages:2d} "
          f"size={bytes_ratio:8.4f} read={read_ratio:8.4f} {verdict}")
