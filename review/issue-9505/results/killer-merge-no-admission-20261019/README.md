# F16 admission ablation

This harness checks F16 after removal of the merge admission selector.
It runs K once with `rewrite_rows` and once with `rewrite_columns`.
U_main supplies the independent oracle. The harness does not repeat the U_main merge that previously reached the 8 GiB limit.

The target contains 16,000,000 rows and 44 Int64 columns across 160 fragments.
The source supplies 100 shuffled matching keys and updates two Int64 columns.
Indexes and conflict retries remain disabled. The requested pool is 1 GiB, and each worker has an 8 GiB cgroup with no swap.
Successful execution must preserve all fields and report exactly 100 updates.

Use a new result directory and freeze the new binary. Do not modify the original main benchmark or admission results.
The `K` label maps to the candidate checkout supplied during `init`, normally `/mnt/lance/checkouts/K_check`.
Use its final optimized extension build log for `--build-log K=...`.
Check the production diff before calling this an ablation of the selector alone.

## Reuse the fixture

Use `import-fixture --source-root /mnt/lance/killer-merge-20261018` after `freeze`.
This command checks the complete F16 file set, its hashes, its specification, and its fragment count.
It hard-links immutable `.lance` files and copies metadata into the new directory.
It checks the copied files and saves only the original F16 entries in `fixture-hashes.json`.
The source and destination must reside on the same filesystem for hard links.
The local evidence mirror has no datasets. Import from the original remote result directory.

Each measured cell still receives its own dataset directory. The oracle runs in a separate U_main process.
Fixture import and verification occur outside the API timer. No fixture generation or build is necessary.

## Commands

Copy `harness.py`, `fixtures.py`, and this README into `/mnt/lance/killer-merge-no-admission-20261019`.
Prepare an empty cgroup parent at `/sys/fs/cgroup/lance-killer-no-admission`.
Enable the `cpu` and `memory` controllers in the root and parent cgroups.
Keep the coordinator outside the parent cgroup. Do not run another benchmark or build concurrently.

Run these commands from `/mnt/lance/checkouts/K_check/python` after sourcing `/mnt/lance/env.sh`.
Wait for the optimized K_check extension build log below to report success.

```sh
ablation_root=/mnt/lance/killer-merge-no-admission-20261019
ablation_build_log=/mnt/lance/killer-merge-no-admission-20261019/logs/K-build.log
test -s "$ablation_build_log"
uv run --no-sync python -m py_compile \
  "$ablation_root/harness.py" "$ablation_root/fixtures.py"
uv run --no-sync python "$ablation_root/harness.py" init \
  --baseline /mnt/lance/checkouts/U_main --candidate /mnt/lance/checkouts/K_check \
  --base-commit 0a0d327082988018a25f56147d3b6d02f6c79ecc \
  --cgroup /sys/fs/cgroup/lance-killer-no-admission \
  --build-log U_main=/mnt/lance/killer-merge-20261018/logs/U_main-build.log \
  --build-log "K=$ablation_build_log"
uv run --no-sync python "$ablation_root/harness.py" freeze
uv run --no-sync python "$ablation_root/harness.py" import-fixture \
  --source-root /mnt/lance/killer-merge-20261018
uv run --no-sync python "$ablation_root/harness.py" run ablation
uv run --no-sync python "$ablation_root/harness.py" summarize
```

The run writes `gate-ablation.json` and `summary.json`.
Any candidate failure stops the stage immediately, including a verified resource failure.
The parent agent must inspect the failure before deciding whether to measure the remaining mode separately.
An abort such as exit 134 remains an infrastructure error. Do not reclassify it from an exception message alone.
Retain any separate post-failure atomicity check without rewriting the original result.

## Reverse workload

For the new reverse check, copy the original admission harness scripts into another new result directory.
Use `--candidate /mnt/lance/checkouts/K_check` and the new optimized build log during `init`.
Keep its 256 MiB pool and `R_admission` workload unchanged.
Do not copy the old `config.json`, `freeze.json`, gate files, or run directories.

This harness was prepared without execution. Run the syntax check before importing fixtures.
