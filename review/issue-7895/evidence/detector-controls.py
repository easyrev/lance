"""Check both replay detection and conservative scanner fallback before timing."""

import argparse
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--baseline", required=True, type=Path)
parser.add_argument("--candidate", required=True, type=Path)
parser.add_argument("--fixture", required=True, type=Path)
parser.add_argument("--run-id", default="final")
args = parser.parse_args()
evidence = Path(__file__).parent
fixture = json.loads((args.fixture / "fixture.json").read_text())
assert fixture["arrow_bytes"] < 100 * 1024 * 1024
output = evidence / "controls" / args.run_id
output.mkdir(parents=True)
cases = [
    ("oneshot", False, 3), ("oneshot", True, 3), ("table", False, 3),
    ("lance", True, 3), ("arrow", True, 3), ("scanner", True, 3),
    ("lance", True, 0),
]
observations = []
for label, package in (("baseline", args.baseline), ("candidate", args.candidate)):
    package_hashes = set()
    for kind, conflict, retries in cases:
        case = f"{kind}-{'conflict' if conflict else 'clean'}-retries{retries}"
        trial_id = f"controls-{args.run_id}-{args.fixture.name}-{label}-{case}"
        command = [str(evidence / "run-trial.sh"), trial_id, "--package", str(package),
                   "--label", f"controls-{args.run_id}-{label}", "--root", str(args.fixture),
                   "--kind", kind, "--trial", case, "--retries", str(retries)]
        if conflict:
            command.append("--conflict")
        with (output / f"{label}-{case}.jsonl").open("w") as stdout, (output / f"{label}-{case}.stderr").open("w") as stderr:
            subprocess.run(command, stdout=stdout, stderr=stderr, check=True)
        result = json.loads((output / f"{label}-{case}.jsonl").read_text())
        expected_replay = int(retries > 0 and kind != "table" and
                              (label == "baseline" or kind in ("oneshot", "scanner")))
        assert result["replay_directory_count"] == expected_replay, result
        assert result["spill_file_count"] == 0, result
        assert result["spill_file_unlink_bytes"] == 0, result
        assert result["correct"], result
        if retries == 0:
            assert result["error"]["type"] == "OSError", result
            assert "Too many concurrent writers" in result["error"]["message"], result
        elif conflict:
            assert result["commit_versions"] == [2, 3], result
            assert result["concurrent_versions"] == [2], result
            assert result["final_version"] == 3, result
        package_hashes.add(result["extension_sha256"])
        observations.append({"label": label, "case": case,
                             "expected_replay_directory_count": expected_replay,
                             "actual_replay_directory_count": result["replay_directory_count"],
                             "extension_sha256": result["extension_sha256"], "passed": True})
    assert len(package_hashes) == 1, package_hashes
(output / "summary.json").write_text(json.dumps(observations, indent=2) + "\n")
print(f"All {len(observations)} detector controls passed: {output / 'summary.json'}")
