"""Check downloaded files against the ECS digest manifest and query records."""

import hashlib
import json
from pathlib import Path

delivery = Path(__file__).resolve().parent
root = delivery / "results"
records = json.loads((delivery / "remote-sha256.json").read_text())
for relative, expected in records.items():
    path = root / relative
    assert path.is_file(), relative
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    assert path.stat().st_size == expected["bytes"], relative
    assert digest.hexdigest() == expected["sha256"], relative

samples = []
invocations = {}
groups = {}
for path in sorted((root / "measurement").glob("*-session-*.jsonl")):
    batch = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(batch) == 25, path
    assert sum(item["warmup"] for item in batch) == 5, path
    round_id = path.name.split("-", 1)[0]
    invocations[(round_id, batch[0]["cache"], batch[0]["label"])] = batch
    for item in batch:
        if not item["warmup"]:
            key = (item["cache"], item["label"])
            groups[key] = groups.get(key, 0) + 1
    samples.extend(batch)

assert len(samples) == 500
assert len(groups) == 4 and set(groups.values()) == {100}
for (round_id, cache, label), batch in invocations.items():
    other = invocations[(round_id, cache, "fixed" if label == "baseline" else "baseline")]
    assert [item["id"] for item in batch] == [item["id"] for item in other]
for item in samples:
    expected_rows = 4_000_000 if item["label"] == "baseline" else 1
    assert item["all_counts"]["rows_scanned"] == expected_rows

for phase in ["fixed-tests-final", "index-tests-final", "resolver-tests", "fixed-lint-final", "example-lint-default-final-v2", "fixed-build", "measurement"]:
    assert (root / phase / "exit.code").read_text().strip() == "0", phase

report = {
    "copied_files_verified": len(records),
    "copied_bytes_verified": sum(item["bytes"] for item in records.values()),
    "queries": len(samples),
    "timed_queries": 400,
    "warmup_queries": 100,
    "paired_query_ids_match": True,
    "sha256_match": True,
}
(delivery / "integrity-check.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
