"""Extract observed latency phases from separate slow-source diagnostics."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SYSCALL = re.compile(r"^(\d+\.\d+) (read|pread64|write)\(\d+<([^>]+)>")


def main():
    initial = set(json.loads((ROOT / "fixtures/tiny/fixture.json").read_text())["files"])
    rows = []
    for directory in sorted((ROOT / "runs").glob("g1-slow-*")):
        metrics = json.loads((directory / "metrics.json").read_text())
        start = metrics.get("execute_started_wall_ns", 0) / 1e9
        producer = [json.loads(line) for line in (directory / "producer.jsonl").read_text().splitlines()]
        first_read = first_write = None
        for trace in directory.glob("io.trace.*"):
            for line in trace.read_text(errors="replace").splitlines():
                match = SYSCALL.match(line)
                if not match:
                    continue
                timestamp, call, name = match.groups()
                timestamp = float(timestamp)
                if timestamp < start:
                    continue
                if call in ("read", "pread64") and name in initial:
                    first_read = timestamp if first_read is None else min(first_read, timestamp)
                if call == "write" and "/fixtures/tiny/data/" in name and name.endswith(".lance") and name not in initial:
                    first_write = timestamp if first_write is None else min(first_write, timestamp)
        evidence_path = directory / "candidate.jsonl"
        evidence = [json.loads(line) for line in evidence_path.read_text().splitlines()] if evidence_path.exists() else []
        plans = [event["unix_seconds"] for event in evidence if event.get("phase") == "physical_plan"]
        rows.append(dict(run_id=directory.name, variant=metrics["variant"], status=metrics["status"],
                         merge_seconds=metrics.get("merge_seconds"),
                         source_prepare_seconds=metrics.get("source_prepared", {}).get("seconds"),
                         first_producer_ready_seconds=min((event["wall_ns"] / 1e9 - start for event in producer if event["event"] == "ready"), default=None),
                         first_planning_complete_seconds=min(plans) - start if plans else None,
                         first_target_file_read_seconds=first_read - start if first_read else None,
                         first_output_data_file_write_seconds=first_write - start if first_write else None,
                         trace_limit="read/pread64/write syscalls only; missing observations remain null; target read includes footer reads"))
    (ROOT / "latency-results.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
