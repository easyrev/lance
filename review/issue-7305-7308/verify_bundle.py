"""Verify the IVF review publication without building Lance."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote


def main():
    root = Path(__file__).resolve().parent
    repo = root.parent.parent
    manifest = json.loads((root / "publication-manifest.json").read_text())
    expected = set(manifest["files"])
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != "publication-manifest.json"
    }
    assert actual == expected, "The published file set differs from the manifest"
    for name, metadata in manifest["files"].items():
        content = (root / name).read_bytes()
        assert len(content) == metadata["bytes"], name
        assert hashlib.sha256(content).hexdigest() == metadata["sha256"], name

    links = 0
    for path in root.rglob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if target.startswith(("https://", "http://", "#")):
                continue
            local = unquote(target.split("#", 1)[0])
            assert not Path(local).is_absolute(), (path, target)
            assert (path.parent / local).exists(), (path, target)
            links += 1

    for name, expected_hash in manifest["candidate_source_sha256"].items():
        content = subprocess.check_output(
            ["git", "show", f"{manifest['code_candidate']}:{name}"], cwd=repo
        )
        assert hashlib.sha256(content).hexdigest() == expected_hash, name
        assert (repo / name).read_bytes() == content, name

    cases = [
        json.loads(line)
        for line in (root / "evidence/resource-diagnostic.jsonl")
        .read_text()
        .splitlines()
    ]
    assert len(cases) == 6
    assert {(c["distribution"], c["budget_bytes"]) for c in cases} == {
        (distribution, budget)
        for distribution in ("uniform", "hotspot")
        for budget in (0, 8388608, 33554432)
    }
    for case in cases:
        assert case["debug_assertions"]
        assert case["rows"] == 262144 and case["dimensions"] == 64
        assert case["row_id_checksum"] == 34359607296
        assert case["vector_bits_checksum"] == 17662399169384832
        assert case["spill_files_created"] == 4
        assert case["pool_final_bytes"] == 0
        assert case["spill_final_live_bytes"] == 0
        assert case["spill_final_live_files"] == 0
        if case["budget_bytes"]:
            assert case["pool_peak_bytes"] <= case["budget_bytes"]
            assert case["flushes"] == {8388608: 32, 33554432: 8}[case["budget_bytes"]]

    print(f"Verified {len(expected)} file hashes and {links} local Markdown targets.")
    print("Verified candidate source files and all six diagnostic records.")
    print("Historical execution provenance is not established by these hashes.")


if __name__ == "__main__":
    main()
