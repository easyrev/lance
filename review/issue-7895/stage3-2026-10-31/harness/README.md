# #9617 Stage 3 benchmark harness

This directory is outside the PR worktree. It uses the three preflight wheels:

| Build | Commit | Wheel SHA256 |
|---|---|---|
| U | `f9a5c662d79ac312d16d8f636cb1feba4e84aee8` | `e6b3c0b15f816027d757430cca09b7b08b92ebc0e67d905b30cd5e65ea33d6fc` |
| P1 | `15a523ffcc93e6d2c73ad2af69a1e6420efcdc22` | `28e861a077701abbbf97a924525bf6ab1d70c06674bc1bfe4874e0917294d73a` |
| P2 | `9767241c21d4124dc2f8d24d642abe93c8ca859c` | `5b9945c84d399258ebe04d7a5cad604f03d846666d76559458e0e3aa8e478e05` |

The wheel build profile is Cargo `release` through `maturin build --release`.

The parent starts one child for each run. It uses `wait4` to record user CPU, system CPU, and peak RSS. The child measures wall time only around `execute()`. A sampler records the peak size of the run-specific `TMPDIR`.

Each run verifies the row count, version count, and sampled values for every column. The worker then restores the tagged first version and removes untagged intermediate versions.

For OSS runs, the child calls `load_oss_env()` before it imports Lance or PyArrow. It reads `/root/.lance-bench/oss.env`. No credential value goes to stdout, stderr, JSON, or reports.

Lance uses `oss://` with the native internal endpoint. PyArrow uses the S3-compatible internal endpoint with virtual addressing.

Run one cell:

```bash
/mnt/lance/9617-bench/bin/bench_parent.py \
  --build P2 \
  --spec /mnt/lance/9617-bench/fixtures/spec.json \
  --run-number 1 \
  --tag smoke-P2-1
```

Collect all JSON files:

```bash
python /mnt/lance/9617-bench/bin/summarize.py /mnt/lance/9617-bench/results
```
