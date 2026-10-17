"""Capture actual source-dependent analyze_plan output outside benchmark timing."""

import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--package", required=True)
parser.add_argument("--label", required=True)
parser.add_argument("--root", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
sys.path.insert(0, args.package)

import lance  # noqa: E402
import lance.lance as native  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.dataset as pads  # noqa: E402

pa.set_cpu_count(4)
pa.set_io_thread_count(4)
fixture = json.loads((args.root / "fixture.json").read_text())
extension_sha256 = hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest()

for kind in ("lance", "arrow", "scanner"):
    output = args.output / args.root.name / args.label / kind
    output.mkdir(parents=True)
    target_path = output / "target.lance"
    shutil.copytree(args.root / "target-template.lance", target_path)
    commits = []

    @contextlib.contextmanager
    def lock(version):
        commits.append(version)
        yield

    target = lance.dataset(target_path, commit_lock=lock)
    before_version = target.version
    before_table = target.to_table()
    before_versions = target.versions()
    if kind == "lance":
        source = lance.dataset(args.root / "source.lance")
        source_config = {"type": "LanceDataset", "version": source.version}
    else:
        source = pads.dataset(args.root / "source.parquet", format="parquet")
        source_config = {"type": "pyarrow.dataset.Dataset", "format": "parquet"}
        if kind == "scanner":
            source = source.scanner(batch_size=4096, use_threads=False)
            source_config = {"type": "pyarrow.dataset.Scanner", "format": "parquet",
                             "batch_size": 4096, "use_threads": False}
    plan = (target.merge_insert("id").when_matched_update_all()
            .when_not_matched_insert_all().conflict_retries(3).analyze_plan(source))
    latest = lance.dataset(target_path)
    assert not commits, commits
    assert latest.version == before_version == 1
    assert latest.versions() == before_versions
    assert latest.to_table().equals(before_table)
    assert before_table.num_rows == 1
    assert before_table["value"].to_pylist() == [0]
    (output / "actual-plan.txt").write_text(plan + "\n")
    topology = re.sub(r", metrics=\[[^\n]*", "", plan)
    topology = re.sub(r"elapsed=[^,\n]+,? ?", "", topology)
    topology = topology.replace(str(target_path), "<target>").replace(str(target_path).lstrip("/"), "<target>")
    topology = topology.replace(str(args.root), "<fixture>").replace(str(args.root).lstrip("/"), "<fixture>")
    topology = "\n".join(line.rstrip(", ") for line in topology.splitlines()) + "\n"
    (output / "topology.txt").write_text(topology)
    record = {
        "label": args.label, "kind": kind, "fixture": fixture,
        "package": lance.__file__, "extension": native.__file__,
        "extension_sha256": extension_sha256, "pyarrow": pa.__version__,
        "source_config": source_config, "commit_versions": commits,
        "before_version": before_version, "after_version": latest.version,
        "target_unchanged": True,
        "operators": [line.strip().split(":", 1)[0] for line in topology.splitlines() if line.strip()],
    }
    (output / "metadata.json").write_text(json.dumps(record, indent=2) + "\n")
    shutil.rmtree(target_path)
    print(json.dumps(record))
