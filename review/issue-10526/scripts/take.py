import argparse
import json
import resource
import time
from pathlib import Path

import lance
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("dataset", type=Path)
parser.add_argument("count", type=int)
parser.add_argument("--dataset-rows", required=True, type=int)
parser.add_argument("--repeat", type=int, default=1)
parser.add_argument("--take-only", action="store_true")
parser.add_argument("--perf-control", nargs=2)
args = parser.parse_args()
rows = sorted(
    np.random.default_rng(10526).choice(args.dataset_rows, args.count, replace=False).tolist()
)
if args.take_only:
    dataset = lance.dataset(args.dataset)
if args.perf_control:
    control = open(args.perf_control[0], "w", buffering=1)
    acknowledgement = open(args.perf_control[1])
    control.write("enable\n")
    assert acknowledgement.readline().strip() == "ack"
for _ in range(args.repeat):
    start = time.perf_counter_ns()
    if not args.take_only:
        dataset = lance.dataset(args.dataset)
    opened = time.perf_counter_ns()
    result = dataset.take(rows)
    finished = time.perf_counter_ns()
    assert result.num_rows == args.count
    print(
        json.dumps(
            {
                "rows": args.count,
                "open_ms": (opened - start) / 1e6,
                "take_ms": (finished - opened) / 1e6,
                "process_peak_rss_kib": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss,
                "indices": rows,
            }
        ),
        flush=True,
    )

if args.perf_control:
    control.write("disable\n")
    acknowledgement.readline()
