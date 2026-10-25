# Reproduce staged index coverage measurements

The baseline is `fc5cb646e647e0cdd497fa1cf8ce0c6f25abeb75` from upstream main.
Use the same benchmark source for the baseline and the patch.
The source is `staged_coverage_bench.rs` in this directory.
The local baseline checkout is `output/issue10096/baseline`.
The local patch checkout is `output/issue10096/worktree`.
The benchmark harness stays outside the proposed PR diff. Copy it into each checkout before compilation.

Run compilation, tests, and measurements on Linux through `ssh lance-ecs`.
Keep all source edits local. Use `output/ecs-dev/sync.py` to transfer each snapshot.
The remote task name is `issue10096`. Do not reuse that name for another task.
The runner takes the worktree lock before the exclusive host lock.
It then sources `/mnt/lance/tools/env.sh`.

1. Place the benchmark source at `rust/lance/examples/staged_coverage_bench.rs` in each local checkout.
2. Synchronize the baseline checkout.
3. Deploy `run.sh` to `/mnt/lance/results/issue10096-run.sh`.
4. Run the baseline build in tmux.
5. Retrieve or retain its executable before synchronizing the patch.
6. Synchronize the patch checkout.
7. Run the patch tests, lint, and optimized build in tmux.
8. Deploy `measure.sh` to `/mnt/lance/results/issue10096-measure.sh`.
9. Run the measurement in tmux after all builds and tests finish.

Example synchronization:

```sh
python3 output/ecs-dev/sync.py issue10096 --source /path/to/local/checkout
```

The runner records commands, source archives, the base revision, working diffs, logs, and exit codes.
Use a new phase name when repeating a command. Keep earlier failures.

```sh
ssh lance-ecs 'tmux new-session -d -s lance-issue10096-build "bash /mnt/lance/results/issue10096-run.sh baseline-build-verified"'
ssh lance-ecs 'tmux new-session -d -s lance-issue10096-tests "bash /mnt/lance/results/issue10096-run.sh fixed-tests"'
ssh lance-ecs 'tmux new-session -d -s lance-issue10096-lint "bash /mnt/lance/results/issue10096-run.sh fixed-lint"'
ssh lance-ecs 'tmux new-session -d -s lance-issue10096-fixed-build "bash /mnt/lance/results/issue10096-run.sh fixed-build"'
ssh lance-ecs 'tmux new-session -d -s lance-issue10096-measure "bash /mnt/lance/results/issue10096-measure.sh"'
```

The build command uses the repository profile without CPU or LTO overrides:

```sh
cargo build --locked -p lance --no-default-features --profile release-with-debug --example staged_coverage_bench
```

Run the required workspace lint with default features.
Check the manual benchmark separately with the same defaults.
Its expected plan output uses stderr, which the final command explicitly permits.

```sh
cargo clippy --all --tests --benches -- -D warnings
cargo clippy --locked -p lance --example staged_coverage_bench -- -D warnings -A clippy::print_stderr
```

The measurement uses 4,000,000 rows with two Int64 columns.
`id` increases from zero. `val = (id * 48271) % 2147483647`.
The write limit is 250,000 rows per fragment.
Deferred compaction targets 500,000 rows per fragment.
A committed `id_idx` causes compaction to retain v0 FRI records.
The `val_idx` segment is staged before compaction and published afterward from a fresh dataset.

The baseline executable creates one fixture and serializes the staged metadata.
The script copies that fixture for each publication variant.
Both copies contain the same data and index files before publication.
Each query checks its returned `id` and `val`.

The script holds the exclusive host lock throughout measurement.
It rejects a detected cargo, rustc, pytest, or maturin process before measurement.
It records process inventories before and after measurement.

Each query invocation first scans both columns with scalar indices disabled.
This warms the OS page cache. The script does not measure cold storage.
`fresh-session` creates a new Lance session before each query.
`warm-session` reuses a Lance session.
Dataset opening and the initial full scan are outside the query timer.
The timer includes query construction, planning, and execution.

Each invocation discards five warmup queries and records twenty query samples.
Five rounds alternate the baseline and patch order.
Each cache mode therefore contains 100 measured queries per variant.
Raw JSONL files contain latency, storage bytes, plan bytes, and execution counters.
Analyzed plans remain in separate text files.
Storage read counters measure API bytes, including reads served by the OS cache.
They do not measure physical disk traffic.

Summarize downloaded measurements:

```sh
python3 output/issue10096/summarize.py output/issue10096/results/measurement
```

The fixture archive and staged protobuf permit repetition without regenerating data.
Extract fresh fixture copies before repeating publication.
Use new result directories to preserve earlier results.

The measurement covers selective BTree equality queries after one deferred compaction.
It does not establish gains for vector search, remote storage, cold caches, or other workloads.
