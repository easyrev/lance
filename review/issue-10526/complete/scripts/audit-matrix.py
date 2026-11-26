import json
import sys
from pathlib import Path

raw = Path(sys.argv[1])
phase = sys.argv[2]
phase1_rows = {
    "utf8-1page": 25000, "utf8-zstd-25k": 25000, "utf8-zstd-8k": 8000,
    "binary-zstd-varlen": 12000, "binary-random-varlen": 12000,
    "binary-zstd-medium": 99650, "binary-medium-default": 99650, "mixed": 16000,
}
phase2_rows = {
    "wide-unique": 25000, "wide-unique-8k": 8000, "wide-low-card": 25000,
    "wide-repeated": 8000, "wide-template": 25000, "wide-clustered": 25000,
    "wide-mixed": 25000, "wide-constant": 25000, "narrow": 10000000,
}
rows = phase1_rows if phase == "phase1" else phase2_rows
variants = ("base", "pure", "var") if phase == "phase1" else ("base", "final", "final-b")
case_count = process_count = precision_count = 0
for dataset, row_count in rows.items():
    for variant in variants if phase == "phase1" else ("final-b",):
        with (raw / f"{phase}-verify-{dataset}-{variant}.json").open() as stream:
            exact = json.load(stream)
        assert exact["scan_rows"] == exact["take_rows"] == row_count, (dataset, variant)
        precision_count += 1
    if phase == "phase1":
        operations = ("scan", "take128") if dataset == "utf8-zstd-8k" else ("scan", "take128", "take1024")
    else:
        operations = ("scan", "take", "repeat128", "repeat1024") if dataset == "wide-unique" else ("scan", "take")
    for operation in operations:
        case_count += 1
        selected = None
        repeated = (operation.startswith("take") and phase == "phase1") or operation.startswith("repeat")
        count = 5 if (raw / f"{phase}-{operation}-{dataset}-5-{variants[0]}.jsonl").exists() else 3
        for trial in range(1, count + 1):
            for variant in variants:
                path = raw / f"{phase}-{operation}-{dataset}-{trial}-{variant}.jsonl"
                records = [json.loads(line) for line in path.read_text().splitlines()]
                assert len(records) == (20 if repeated else 1), path
                for record in records:
                    if operation == "scan":
                        assert record["rows"] == row_count, path
                        continue
                    indices = record["indices"]
                    count_wanted = 1024 if operation.endswith("1024") else 128
                    assert len(indices) == count_wanted == record["rows"], path
                    assert indices == sorted(set(indices)), path
                    assert min(indices) >= 0 and max(indices) < row_count, path
                    if selected is None:
                        selected = indices
                    assert selected == indices, path
                process_count += 1
        print(f"{dataset} {operation} {count} processes per build")
print(f"Total cases: {case_count}; timed processes: {process_count}; exactness records: {precision_count}")
