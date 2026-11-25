from pathlib import Path
import re
from collections import Counter
import sys

for path in sorted(Path(sys.argv[1]).glob("pread-*.log")):
    pending = {}
    calls = Counter()
    for line in path.read_text().splitlines():
        thread, _, entry = line.partition(" ")
        if entry.startswith("pread64("):
            pending[thread] = ".lance>" in entry.partition(",")[0]
        elif not entry.startswith("<... pread64 resumed>"):
            continue
        match = re.search(r"\) += (\d+) <", entry)
        if match and pending.pop(thread, False):
            calls[int(match[1])] += 1
    print(
        path.name,
        "calls",
        sum(calls.values()),
        "bytes",
        sum(k * v for k, v in calls.items()),
        "under 8KiB",
        sum(v for k, v in calls.items() if k < 8192),
        "32KiB+",
        sum(v for k, v in calls.items() if k >= 32768),
        "sizes",
        calls.most_common(8),
    )
