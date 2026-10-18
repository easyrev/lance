# Merge admission counterexample

This directory contains an independent harness for the target admission heuristic.
It reuses the existing U_main and K Python extensions. It does not modify the frozen main benchmark.

The target contains 1,000,000 rows and 44 Int64 columns across ten fragments.
The source contains 3,000,000 rows with the same schema. A lazy RecordBatchReader supplies batches of 32,768 rows.
Expected output contains 3,000,000 rows: 1,000,000 updates and 2,000,000 inserts.
The operation uses `rewrite_rows`, disables indexes, and sets conflict retries to zero.

Each variant runs once. The requested pool is 256 MiB. Each worker has an 8 GiB cgroup limit and no swap.
U_main can use an unbounded pool on this path. The configured value does not prove that U_main enforces it.

The target match projection is narrow even though the stored rows have 44 columns.
The raw source values occupy 1,056,000,000 bytes before Arrow and join overhead.
This case challenges the choice to build an unknown source when the target estimate exceeds one quarter of the pool.
Both variants use the same full-field oracle in a separate U_main process.
Resource failures require an unchanged snapshot and unchanged data. Failures without a recorded snapshot stop as infrastructure errors.

## Run

Run after the main benchmark finishes. Do not build or run another benchmark concurrently.
Copy only `harness.py`, `fixtures.py`, and this README into a new remote directory.
Use `/mnt/lance/killer-merge-admission-check` and a new parent cgroup, `/sys/fs/cgroup/lance-killer-admission`.
The existing checkouts must already satisfy `python/AGENTS.md`. No environment setup or build is needed.

Enable `cpu` and `memory` in the root and parent cgroups before running the harness.
The parent cgroup must contain no processes. Keep the coordinator outside it.
Check child control files and process membership before accepting resource evidence.

Run these commands from `/mnt/lance/checkouts/K/python` after sourcing `/mnt/lance/env.sh`:

```sh
uv run --no-sync python -m py_compile \
  /mnt/lance/killer-merge-admission-check/harness.py \
  /mnt/lance/killer-merge-admission-check/fixtures.py
uv run --no-sync python /mnt/lance/killer-merge-admission-check/harness.py init \
  --baseline /mnt/lance/checkouts/U_main --candidate /mnt/lance/checkouts/K \
  --base-commit 0a0d327082988018a25f56147d3b6d02f6c79ecc \
  --cgroup /sys/fs/cgroup/lance-killer-admission \
  --build-log U_main=/mnt/lance/killer-merge-20261018/logs/U_main-build.log \
  --build-log K=/mnt/lance/killer-merge-20261018/logs/K-build.log
uv run --no-sync python /mnt/lance/killer-merge-admission-check/harness.py freeze
uv run --no-sync python /mnt/lance/killer-merge-admission-check/harness.py generate
uv run --no-sync python /mnt/lance/killer-merge-admission-check/harness.py run admission
uv run --no-sync python /mnt/lance/killer-merge-admission-check/harness.py summarize
```

The run writes `gate-admission.json` and `summary.json`. A candidate failure returns a nonzero exit status after saving both files.
Retain the exact exception, resource events, validation result, source identity, and extension hash.
Do not repeat a failed cell or replace its output. Use a new result directory for changed sources or binaries.

## Interpretation

U_main success with a K resource failure establishes a regression for this workload and configuration.
It does not establish which implementation change caused the failure. The bounded execution context also differs between the variants.
Use the exact error and execution evidence to distinguish join selection from other resource costs.
One execution per variant does not support a stable latency estimate or a speedup claim.
Initial files are warm. RSS and cgroup charged memory remain separate measurements.

This harness was prepared without execution. Run the syntax check before fixture generation.
