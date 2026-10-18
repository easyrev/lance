# Final merge validation after selector removal

This harness compares the unchanged current-main build (`U_main`) with the new
implementation (`K`, mapped to `K_check`). It never loads the historical C experiment flags. All
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

Copy only `harness.py`, `fixtures.py`, and this README into a new result directory,
`/mnt/lance/killer-merge-final-20261019`; do not reuse any historical result root.
Use the same compiler, profile, CPU flags and dependency lockfiles for both
variants. Wait for the final optimized K_check extension build and required tests
to finish. The commands below run from `/mnt/lance/checkouts/K_check/python`
after `source /mnt/lance/env.sh`.

Prepare the cgroup parent before initialization. The cgroup v2 root is exempt
from the no-internal-process rule; the experiment parent must contain no
processes before its controllers are enabled. Keep the coordinator outside it.
Do not substitute ordinary files for missing cgroup controls. These checks fail
if memory isolation is unavailable.

```sh
set -eu
test "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs
printf '+cpu +memory\n' > /sys/fs/cgroup/cgroup.subtree_control
mkdir /sys/fs/cgroup/lance-killer-final
test -z "$(cat /sys/fs/cgroup/lance-killer-final/cgroup.procs)"
printf '+cpu +memory\n' > /sys/fs/cgroup/lance-killer-final/cgroup.subtree_control
mkdir /sys/fs/cgroup/lance-killer-final/preflight
test -f /sys/fs/cgroup/lance-killer-final/preflight/memory.max
test -f /sys/fs/cgroup/lance-killer-final/preflight/memory.swap.max
test -f /sys/fs/cgroup/lance-killer-final/preflight/memory.oom.group
test -f /sys/fs/cgroup/lance-killer-final/preflight/cpu.max
rmdir /sys/fs/cgroup/lance-killer-final/preflight
```

The result directory and prior fixtures must be on the same filesystem because
immutable data files are hard-linked. The local evidence mirror has no datasets;
use the original remote result directory for `--prior-failure-root`.

```sh
final_root=/mnt/lance/killer-merge-final-20261019
final_build_log=/mnt/lance/killer-merge-no-admission-20261019/logs/K-build.log
test -s "$final_build_log"
uv run --no-sync python -m py_compile "$final_root/harness.py" "$final_root/fixtures.py"
uv run --no-sync python "$final_root/harness.py" init \
  --baseline /mnt/lance/checkouts/U_main --candidate /mnt/lance/checkouts/K_check \
  --base-commit 0a0d327082988018a25f56147d3b6d02f6c79ecc \
  --cgroup /sys/fs/cgroup/lance-killer-final \
  --prior-failure-root /mnt/lance/killer-merge-20261018 \
  --build-log U_main=/mnt/lance/killer-merge-20261018/logs/U_main-build.log \
  --build-log "K=$final_build_log"
uv run --no-sync python "$final_root/harness.py" freeze
uv run --no-sync python "$final_root/harness.py" import-fixtures
uv run --no-sync python "$final_root/harness.py" run correctness
uv run --no-sync python "$final_root/harness.py" run smoke
uv run --no-sync python "$final_root/harness.py" run pairs
uv run --no-sync python "$final_root/harness.py" summarize
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

## Reused fixtures and one inherited failure

`import-fixtures` verifies all nine prior workload definitions, every file name
and SHA256, each saved fixture specification, row count, fragment count and
version. It hard-links immutable `.lance` files and copies metadata, then checks
the destination again. The full original fixture hash manifest is part of the
new freeze. Each run stage verifies the local files against that frozen manifest.
Use this import command instead of `generate`: regenerated files have different
identities and cannot support inheritance of the old failure.

The only inherited execution is the original
`smoke-F16-U_main-rewrite_rows-b0` in `--prior-failure-root`. Freeze and subsequent
verification require the same actual imported baseline extension and source
identity, Python/PyArrow versions, baseline build log, recorded environment,
workload definitions, fixture/oracle module and complete fixture hashes.
They also check the original result and worker identity, exact execution spec,
1 GiB configured pool, 8 GiB cgroup, zero swap, increased `oom_kill` counter,
SIGKILL exit and absence of timeout or cleanup failure.

The separate post-failure U_main oracle must have exited successfully, reopened
that run's dataset at its latest version, verified the initial snapshot, and
checked all 44 fields and zero modifications. The prior frozen harness and
fixture/oracle source hashes are checked; that oracle's full-field contract is
unchanged here. Original result, resources, spec, metrics, oracle, freeze and
fixture-manifest paths and hashes are recorded under `freeze.json.prior_failure`.
A changed binary, configuration, evidence file or fixture rejects inheritance.
This is evidence of an OOM under the 8 GiB cgroup, not proof that U_main enforced
the requested 1 GiB DataFusion pool.

The smoke F16/U_main cell and its three planned pair cells return
`not_repeated_after_resource_failure`. Each writes a `references/*.json` record
with `executed: false` and the prior paths/hashes. They create no execution
directory or fresh result sample. The four references point to **one historical
OOM**, not four measurements. `summary.json.inherited_failures` lists them
separately from `results` and latency ratios. They cannot contribute to sample
counts, failure rates, variance, paired timing or speedup ratios.

With no other failures, the original matrix has 49 planned cells and 45 new
executions: 8 correctness, 13 smoke and 24 pairs. All other U_main and K cells
run freshly. Wn and Ws retain three random-order paired blocks; F16 provides
three fresh K Rows/Columns comparisons and no same-round baseline comparison.

## Minimal matrix

All execute and validate workers use a 1 GiB requested DataFusion pool, an 8 GiB
cgroup and no swap. This is a configured pool, not proof that either binary's
entire memory is tracked. Initial data files are warmed before each measurement.

| Gate | Workload | Variants and modes | Purpose |
| --- | --- | --- | --- |
| correctness | tiny, condition_overlap, condition_reject, string_null | U_main/K, rewrite_rows | Actual execution and full-field oracle before large runs |
| smoke | F16, Wn, Ws, R, dense_safe | U_main/K rows; K columns except R | Fresh execution except the inherited F16/U_main failure |
| pairs | F16, Wn, Ws | U_main rows, K rows, K columns | Three deterministic randomized blocks; F16/U_main is a reference only |

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
