import json
import os
from pathlib import Path
import signal
import sys
import time

group = int(sys.argv[1])
label = sys.argv[2]
stat = Path(f"/proc/{group}/stat")
started = stat.read_text().rsplit(")", 1)[1].split()[19]
log = Path("/workspace/issue-7895-evidence/root-build-disk-monitor.jsonl")

while stat.exists():
    try:
        if stat.read_text().rsplit(")", 1)[1].split()[19] != started:
            break
    except FileNotFoundError:
        break
    usage = os.statvfs("/workspace")
    free = usage.f_bavail * usage.f_frsize
    paused = free < 2 * 1024**3
    with log.open("a") as output:
        output.write(json.dumps({"time": time.time(), "label": label, "group": group,
                                 "free_bytes": free, "paused": paused}) + "\n")
    if paused:
        os.killpg(group, signal.SIGSTOP)
        print(f"Paused {label} group {group}: {free} bytes free", flush=True)
        sys.exit(2)
    time.sleep(5)

print(f"Process group {group} completed; monitor stopped", flush=True)
