"""Generate the one authorized F4 skew fixture, outside measurements."""
import bench

spec = bench.workload("F4") | dict(
    name="F4_skew",
    hot_keys=True,
    fragment_boundaries=[0, 1_800_000, 3_600_000] + list(range(3_650_000, 4_000_001, 50_000)),
)
bench.fixture(spec)
bench.save(bench.ROOT / "skew-workload.json", spec)
