"""Verify the published evidence subset without compiling or contacting ECS."""

import hashlib
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent
delivery = root / "local-delivery"
expected_files = set()
for line in (root / "MANIFEST.sha256").read_text().splitlines():
    expected, relative = line.split("  ", 1)
    expected_files.add(relative)
    assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected, relative
actual_files = {
    path.relative_to(root).as_posix()
    for path in root.rglob("*")
    if path.is_file() and path.name != "MANIFEST.sha256"
}
assert expected_files == actual_files

remote = json.loads((delivery / "remote-sha256.json").read_text())
excluded = json.loads((root / "excluded-artifacts.json").read_text())
assert len(remote) == 259 and len(excluded) == 21
for relative, meta in remote.items():
    if relative in excluded:
        assert meta == excluded[relative]
        continue
    path = delivery / "results" / relative
    assert path.stat().st_size == meta["bytes"], relative
    assert hashlib.sha256(path.read_bytes()).hexdigest() == meta["sha256"], relative

provenance = json.loads((root / "PROVENANCE.json").read_text())
tree = {}
entries = subprocess.check_output(
    ["git", "ls-tree", "-r", "-z", provenance["implementation"]], cwd=root
).split(b"\0")
for entry in filter(None, entries):
    header, name = entry.split(b"\t", 1)
    mode, kind, oid = header.decode().split()
    assert kind == "blob"
    tree[name.decode()] = {"mode": mode, "git_blob": oid}
for phase in provenance["final_tracked_source_equals_implementation"]:
    snapshot = json.loads((root / "source-snapshots" / phase / "manifest.json").read_text())
    for name, meta in tree.items():
        assert all(snapshot[name][key] == value for key, value in meta.items()), (phase, name)
    assert (delivery / "results" / phase / "exit.code").read_text().strip() == "0", phase
assert (delivery / "results/measurement/exit.code").read_text().strip() == "0"
assert (delivery / "results/measurement/working.diff").read_bytes() == (delivery / "local-working.diff").read_bytes()
committed_diff = subprocess.check_output(
    ["git", "diff", "--binary", provenance["baseline"], provenance["implementation"]], cwd=root
)
assert committed_diff == (delivery / "local-working.diff").read_bytes()
assert hashlib.sha256((delivery / "staged_coverage_bench.rs").read_bytes()).hexdigest() == provenance["harness_sha256"]

invocations = {}
groups = {}
for path in sorted((delivery / "results/measurement").glob("*-session-*.jsonl")):
    batch = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(batch) == 25 and sum(item["warmup"] for item in batch) == 5, path
    round_id = path.name.split("-", 1)[0]
    key = (round_id, batch[0]["cache"], batch[0]["label"])
    invocations[key] = batch
    for item in batch:
        expected_rows = 4_000_000 if item["label"] == "baseline" else 1
        assert item["all_counts"]["rows_scanned"] == expected_rows
        if not item["warmup"]:
            group = (item["cache"], item["label"])
            groups[group] = groups.get(group, 0) + 1
assert len(invocations) == 20 and len(groups) == 4 and set(groups.values()) == {100}
for (round_id, cache, label), batch in invocations.items():
    other_label = "fixed" if label == "baseline" else "baseline"
    other = invocations[(round_id, cache, other_label)]
    assert [item["id"] for item in batch] == [item["id"] for item in other]
print(json.dumps({"package_files": len(expected_files), "raw_files_verified": 238,
                  "queries": 500, "timed_queries": 400, "source_correspondence": "passed"}, indent=2))
