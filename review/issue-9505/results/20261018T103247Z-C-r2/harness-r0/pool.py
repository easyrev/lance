"""Final small pool diagnostics. No large-workload or throughput claims."""
import json

import bench

for mode, small in [("Cprep_infinite", False), ("Cprep", False), ("Cprep", True)]:
    directory = bench.ROOT / "diagnostics" / ("pool-" + mode + ("-small" if small else "-large"))
    assert not directory.exists()
    spec = dict(small=small)
    execution = bench.isolated("pool", mode, spec, directory, 2 * bench.GIB, 128 * 1024, diagnostics=True)
    validation = bench.isolated("validate_pool", "U", spec, directory, 2 * bench.GIB, 128 * 1024)
    metric = json.loads((directory / "metrics.json").read_text())
    assert execution["exit_code"] == validation["exit_code"] == 0
    expected = "resource_exhausted" if mode == "Cprep" and not small else "execute_returned"
    assert metric["status"] == expected, metric
    if expected == "resource_exhausted":
        assert "HashJoinInput" in metric["error"]
    print(mode, small, metric["status"], flush=True)
