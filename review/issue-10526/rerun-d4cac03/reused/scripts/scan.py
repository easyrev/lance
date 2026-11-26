import json
import resource
import sys
import time

import lance

path, rows = sys.argv[1:]
start = time.perf_counter()
dataset = lance.dataset(path)
count = 0
for batch in dataset.to_batches(batch_size=1024):
    count += batch.num_rows
assert count == int(rows)
print(json.dumps({
    "rows": count,
    "wall_seconds": time.perf_counter() - start,
    "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
}), flush=True)
