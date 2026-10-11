import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

group = int(sys.argv[1])
group_stat = Path(f"/proc/{group}/stat")
started = group_stat.read_text().rsplit(")", 1)[1].split()[19]
cgroup = Path("/sys/fs/cgroup")
log = Path("/workspace/issue-7895-evidence/perf-candidate-watchdog.jsonl")
last_recorded = 0

while group_stat.exists():
    try:
        if group_stat.read_text().rsplit(")", 1)[1].split()[19] != started:
            break
    except FileNotFoundError:
        break
    usage = os.statvfs("/workspace")
    free = usage.f_bavail * usage.f_frsize
    memory = {
        key: int(value)
        for key, value in (
            line.split() for line in (cgroup / "memory.stat").read_text().splitlines()
        )
    }
    limit = int((cgroup / "memory.max").read_text())
    current = int((cgroup / "memory.current").read_text())
    # Page cache from restored archives is reclaimable and is not an OOM signal.
    working = memory["anon"] + memory["shmem"] + memory["kernel"] - memory["slab_reclaimable"]
    reason = None
    if free < 2 * 1024**3:
        reason = "disk_below_2_gib"
    elif working > limit - int(1.5 * 1024**3):
        reason = "nonreclaimable_memory_within_1_5_gib_of_cgroup_limit"
    now = time.time()
    if reason or now - last_recorded >= 30:
        members = []
        listing = subprocess.check_output(
            ["ps", "-eo", "pid,pgid,rss,stat,comm,args"], text=True
        )
        for line in listing.splitlines()[1:]:
            fields = line.split(maxsplit=5)
            if int(fields[1]) != group or fields[3].startswith("Z"):
                continue
            member = {
                "pid": int(fields[0]), "rss_bytes": int(fields[2]) * 1024,
                "state": fields[3], "command": fields[4],
            }
            args = fields[5].split() if len(fields) > 5 else []
            if "--crate-name" in args:
                member["crate"] = args[args.index("--crate-name") + 1]
            members.append(member)
        row = {
            "time": now, "group": group, "free_bytes": free,
            "cgroup_current_bytes": current, "cgroup_limit_bytes": limit,
            "nonreclaimable_bytes": working,
            "group_rss_bytes": sum(member["rss_bytes"] for member in members),
            "members": members, "paused": reason,
        }
        with log.open("a") as output:
            output.write(json.dumps(row) + "\n")
        last_recorded = now
    if reason:
        os.killpg(group, signal.SIGSTOP)
        print(json.dumps({"paused_group": group, "reason": reason,
                          "free_bytes": free, "nonreclaimable_bytes": working}), flush=True)
        sys.exit(2)
    time.sleep(5)

with log.open("a") as output:
    output.write(json.dumps({"time": time.time(), "group": group, "completed": True}) + "\n")
print(f"Performance build group {group} completed; watchdog stopped", flush=True)
