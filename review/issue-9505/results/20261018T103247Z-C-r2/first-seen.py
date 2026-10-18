"""F4 FirstSeen smoke through Rust: the Python builder has no FirstSeen setter."""
import json
import os
import subprocess

import bench

assert (bench.ROOT / "freeze.json").exists()
assert not subprocess.run(["pgrep", "-x", "rustc"], capture_output=True).stdout
spec = bench.workload("F4") | dict(first_seen=True)
directory = bench.ROOT / "runs/g3-first-seen-F4-Ccore"
assert not directory.exists()
directory.mkdir()
uri = str(bench.ROOT / "fixtures/F4")
subprocess.run(["/root/.local/bin/uv", "run", "--no-sync", "python", "-c",
                "import lance,sys; ds=lance.dataset(sys.argv[1]); ds.checkout_version(1).restore()", uri],
               cwd="/mnt/lance/checkouts/U/python", check=True)
metadata = json.loads((bench.ROOT / "fixtures/F4/fixture.json").read_text())
for name in metadata["files"]:
    with open(name, "rb") as data:
        while data.read(8 * bench.MIB):
            pass
bench.save(directory / "warm-files.json", metadata["files"])
os.environ["LANCE_CANDIDATE_FIRST_SEEN_FIXTURE"] = uri
os.environ["LANCE_CANDIDATE_FIRST_SEEN_METRICS"] = str(directory / "metrics.json")
plan = dict(run_id=directory.name, variant="Ccore", spec=spec, block=0, formal=False,
            pool_bytes=bench.GIB, memory_max_bytes=8 * bench.GIB,
            execution_surface="Rust test binary; mechanism smoke, not Python latency comparison")
bench.append(bench.ROOT / "run-manifest.jsonl", plan | dict(status="planned"))
execution = bench.isolated("first_seen", "Ccore", spec, directory, 8 * bench.GIB, bench.GIB,
                           diagnostics=True, command_override=["/mnt/lance/targets/C/release-with-debug/deps/lance-31a368c8670aef12",
                           "dataset::write::merge_insert::tests::candidate_source::first_seen_preparation_keeps_batch_order",
                           "--exact", "--test-threads=1"])
assert execution["exit_code"] == 0, execution
metrics = json.loads((directory / "metrics.json").read_text())
bench.save(directory / "metrics.json", metrics | plan)
validation = bench.isolated("validate", "U", spec, directory, 8 * bench.GIB, bench.GIB)
status = "validated_success" if validation["exit_code"] == 0 else "validation_error"
bench.save(directory / "metrics.json", metrics | plan | dict(execution=execution, status=status, validated=status == "validated_success"))
bench.append(bench.ROOT / "run-manifest.jsonl", plan | dict(status=status))
assert status == "validated_success", validation
print(status, flush=True)
