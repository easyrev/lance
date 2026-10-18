"""Only the pre-registered near-threshold native pair can expand to nine blocks."""
import json
import random

import bench
from finite import measured

pairs = json.loads((bench.ROOT / "paired-results.json").read_text())
pair = next(pair for pair in pairs if pair["workload"] == "F16" and pair["source"] == "reader" and pair["candidate"] == "Ccore" and pair["control"] == "Cbudget")
assert pair["valid_pairs"] == 5
interval = pair["bootstrap_95_percent_conditional"]
assert .85 <= pair["median_ratio"] <= .95 or interval[0] <= .90 <= interval[1]
order = random.Random(9505 + 9)
for block in range(6, 10):
    variants = ["Cbudget", "Ccore"]
    order.shuffle(variants)
    for variant in variants:
        status = measured(variant, bench.workload("F16"), f"g3-F16-reader-b{block}-{variant}", block, True)
        assert status == "validated_success", status
