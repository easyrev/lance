# Current-main merge validation

This harness compares the unchanged current-main build (`U_main`) with the new
implementation (`K`). It never loads the historical C experiment flags. All
measurements call `MergeInsertBuilder.execute`; no plan-only result counts as an
execution. A run consists of a fresh process, a fresh cgroup and an independent
dataset directory. The unchanged `U_main` binary validates every output row and
field in a separate process.

## Environment and freeze

The coordinator must run on the ECS host after each checkout has completed the
repository's `python/AGENTS.md` setup (`make install`), the optimized
`release-with-debug` build, and the selected Rust/Python correctness checks.
Do not build during measurements. The parent agent owns SSH, building, cgroup
delegation and execution. This directory only supplies the harness.

Copy these files into a new result directory, for example
`/mnt/lance/killer-merge-20261018`; do not reuse any historical result root.
Use the same compiler, profile, CPU flags and dependency lockfiles for both
variants. The example commands run from `K/python` after `source /mnt/lance/env.sh`.

```sh
uv run --no-sync python /mnt/lance/killer-merge-20261018/harness.py init \
  --baseline /mnt/lance/checkouts/U_main --candidate /mnt/lance/checkouts/K \
  --base-commit 0a0d327082988018a25f56147d3b6d02f6c79ecc \
  --cgroup /sys/fs/cgroup/lance-killer-merge \
  --build-log U_main=/path/to/U_main-optimized-build.log \
  --build-log K=/path/to/K-optimized-build.log
uv run --no-sync python /mnt/lance/killer-merge-20261018/harness.py freeze
uv run --no-sync python /mnt/lance/killer-merge-20261018/harness.py generate
uv run --no-sync python /mnt/lance/killer-merge-20261018/harness.py run correctness
uv run --no-sync python /mnt/lance/killer-merge-20261018/harness.py run smoke
uv run --no-sync python /mnt/lance/killer-merge-20261018/harness.py run pairs
uv run --no-sync python /mnt/lance/killer-merge-20261018/harness.py summarize
```

`freeze` records tracked and untracked Rust/Python source hashes, Git identity,
lockfiles, toolchain/build flags, the actual imported extension paths and hashes,
the harness and workload definitions, and machine identity. Each later stage
revalidates these hashes. A changed binary or source requires a new result root.
The unchanged baseline must have the requested base commit and a clean tracked
tree. The candidate must have the same base commit; its patch is frozen as data.
The profile cannot be proved from an extension filename: retain both build logs
and supply their paths with `init --build-log U_main=... --build-log K=...`.

The three run stages are separate gates. Inspect each stage's `gate-*.json`
before advancing. Correctness failures, timeouts and infrastructure errors stop
the stage. A confirmed OOM or resource-exhaustion failure is retained, checked
for an unchanged dataset and not repeated at the same resource setting. A
candidate failure stops progression. Baseline resource failures may leave
candidate-only evidence, but never produce a speedup ratio.
Resource failures before the worker records its initial dataset snapshot are
infrastructure errors and stop the stage; they cannot pass the unchanged check.

## Minimal matrix

All execute and validate workers use a 1 GiB requested DataFusion pool, an 8 GiB
cgroup and no swap. This is a configured pool, not proof that either binary's
entire memory is tracked. Initial data files are warmed before each measurement.

| Gate | Workload | Variants and modes | Purpose |
| --- | --- | --- | --- |
| correctness | tiny, condition_overlap, condition_reject, string_null | U_main/K, rewrite_rows | Actual execution and full-field oracle before large runs |
| smoke | F16, Wn, Ws, R, dense_safe | U_main/K rows; K columns except R | One execution per cell; discover failures and write amplification |
| pairs | F16, Wn, Ws | U_main rows, K rows, K columns | Three deterministic randomized blocks; successful smoke required for each cell |

`dense_safe` preserves 90% physical coverage through repeated target keys, but
uses 400 rows with 64 KiB payloads. It is a separate workload from the old
5 MiB/cell OOM fixture. Its result cannot invalidate the old failure.
`condition_overlap` reads omitted `payload` and `row_marker` to decide which of
64 matched rows update and must then preserve those same columns.
`condition_reject` compares the old binary payload with an empty binary literal
and rejects all 64 matches while preserving the dataset. Both have 256 KiB old payloads.
`string_null` uses string keys, nullable omitted strings, a nullable condition
column and nullable source updates, across three fragments. Null keys are
included and must not match under ordinary SQL equality.

The harness does not force a commit-conflict timing schedule. Retry correctness
is a required Rust test gate, including a refreshed snapshot and invalidated
row addresses. Keep those exact test commands and results beside the build
logs. Likewise, asserting that predicate results are reused and rejected rows
do not issue payload Takes requires implementation-level tests or actual
execution counters; field validation alone cannot establish that mechanism.

## Measurement contract

The API timer includes planning, lazy source production, reading, writing and
commit. Fixture generation, dataset cloning, warming and validation are outside
the timer. Every run stores its complete spec, module identity, expected and
observed action counts, CPU time, sampled RSS, cgroup peak/events, new data-file
bytes, process IO counters, and execution/validation logs. File-byte counts are
the final sizes of new `.lance` files; they exclude manifests, deletions,
temporary writes and future maintenance. `/proc/self/io` is a process counter,
not object-store traffic or complete Lance Take accounting.

The summary reports each status, each valid same-block ratio and write bytes.
It does not average failures away, compare against historical C timings or
choose a universal sink from a single latency number. Baseline/K columns are
not a mechanism ablation; K columns is an existing-writer alternative.

No commands were executed against the new Rust implementation when this
harness was authored. Run `uv run --no-sync python -m py_compile harness.py
fixtures.py` from the prepared environment with the absolute script paths.
Syntax, small-fixture correctness and resource isolation
must be checked on the prepared ECS Python environment before accepting its
performance output.
