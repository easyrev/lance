# Candidate C-r2 execution record

Result root: `/mnt/lance/validation-9505/results/20261018T103247Z-C-r2`.
Implementation: `/mnt/lance/checkouts/C`. No PR or upstream comments are authorized.
The original design, validation brief, and environment handoff are preserved.
C-r1 failed schema-error precedence and is retained in the sibling result directory.
No formal performance samples from C-r1 are used.

Initialize every shell:

```sh
source /mnt/lance/env.sh
source /mnt/lance/proxy.sh
proxy-on
export CARGO_TARGET_DIR=/mnt/lance/targets/C
```

Build and regression checks, from the C root:

```sh
cargo fmt --all
LANCE_ENABLE_UNSTABLE_DATA_OVERLAY_FILES=1 cargo test -p lance --lib --profile release-with-debug dataset::write::merge_insert -- --test-threads=4
cargo test -p lance --lib --profile release-with-debug native_ -- --test-threads=4
cargo clippy -p lance --tests --benches --profile release-with-debug -- -D warnings
```

Optimized Python build, from `C/python` (initial `make install` already completed):

```sh
make -f Makefile -f /mnt/lance/validation-9505/review/issue-9505/harness/profile.mk build UV_RUN='uv run --no-sync'
uv run --no-sync pytest python/tests/test_dataset.py -k merge_insert -q
uv run --no-sync python /mnt/lance/validation-9505/results/20261018T103247Z-C-r2/semantic.py
```

The overlay environment flag is needed for the existing optimized Rust overlay test.
It is not an experiment mode and is not needed by the benchmark fixtures.
The documented benchmark profile and repository CPU flags are retained.

The final read-only reviewer must accept the corrections and test evidence before
`freeze.json` is written. That file records the source, harness and imported extension
hashes. No compilation is allowed while a benchmark case is running.

The coordinator runs through `uv run --no-sync python .../finite.py STAGE` from
`C/python`. Stages are `gate2`, `core3`, `core45`, `boundaries`, `late-smoke`,
`late5`, conditional `budget-late5`, `low`, and `slow`. Review each gate before
advancing. Each stage runs one case at a time. Run IDs refuse overwrite.

Each worker enters a new cgroup under `/sys/fs/cgroup/lance9505-validation`.
The coordinator stays outside. `memory.max`, `memory.swap.max=0`, exit status,
10 ms selected-process RSS samples and whole-group memory events are saved.
Only an incremented `oom_kill` event establishes confirmed OOM.
Validation uses a separate U process after execution resources are saved.

Fixtures reference the sibling C-r1 directory through `fixtures`. Initial data files
are immutable. Each run restores the fixture's recorded initial snapshot before the
API timer, and warms only the recorded initial data files. The skew fixture can have
an initial version greater than one because its fragments are appended separately.

Recover after interruption by reading the last terminal entry in
`run-manifest.jsonl`, preserving its run directory, and checking for active worker
cgroups and Cargo processes. Do not replace failures or reuse run IDs. Continue
only unstarted cells. A source correction requires a new revision and freeze;
do not mix partially completed blocks across different binaries.

Interpretation limits: U does not honor the nominal DF quota on this path.
P is `P_reconstructed`; historical tree equivalence is unverified.
Width-based scan budgets are soft estimates. The observed reservation peak is a
concurrency-dependent lower bound. Payload Take counters measure rows and returned
Arrow memory; they do not cover complete physical storage I/O.

## Completed build, review and test record

The final read-only review is `diagnostics/review-r2.md`, ending with FINAL
CLEARANCE. `freeze.json` was written before Gate 2 and contains the imported
extension identities, all nine changed-source hashes, the complete patch hash,
the reviewed harness hashes and input-document hashes. `C.patch` includes new
files; `C-source.tar.gz` preserves their contents.

The completed optimized Rust checks were 357 merge tests, nine tests selected by
`native_`, 23 forced-Late lineage tests and 21 forced-Late FirstSeen tests. The
native selection includes three existing unrelated index tests. The final
Python merge selection passed 38 tests. `semantic.py` passed 12 strict Early/Late
cases. `pool.py` passed its three expected-state diagnostics, including bounded
failure at HashJoinInput and unchanged snapshot contents. See the separate logs.

The test binary predates exactly two visibility lint corrections. Its hash and
`test-binary-to-final-visibility.patch` document that exception. The reviewer
accepted it as mechanism evidence. The final Python extension includes those
corrections. Clippy passed with warnings denied for the lance crate, its tests
and benches; this was not a workspace-wide Clippy run. Formatting passed.
No Python source in the repository changed; external benchmark scripts are
preserved in this result directory.

The first final Python build failed with E0463 from stale un-hashed lance_arrow
artifacts after feature-dependent test/lint builds. The recovery changed only
`rust/lance-arrow/src/lib.rs`'s mtime, then repeated the same prescribed make
build. File content did not change. The successful retry took 16m32s. Preserve
`logs/C-final-build-cache-failure.log`, `logs/C-final-build-retry.log`, and
`logs/build-cache-recovery.md`. No clean, toolchain substitution, or profile
substitution was used.

Commands for the additional completed correctness checks, from C/python:

```sh
LANCE_ENABLE_UNSTABLE_DATA_OVERLAY_FILES=1 uv run --no-sync pytest python/tests/test_dataset.py -k merge_insert -q
uv run --no-sync python /mnt/lance/validation-9505/results/20261018T103247Z-C-r2/pool.py
```

The forced-Late Rust selections used the frozen optimized test binary directly;
see the named logs and `logs/test-binary-source-state.json`. They did not
compile during measurement. The final make build completed before freezing.

`finite.py` rechecks frozen source, harness and extension hashes at each stage.
Before the separate FirstSeen helper, also verify the frozen test-binary hash.
`summarize.py` writes all terminal states and successful same-block ratios;
`latency.py` extracts only observed trace phases. Missing trace phases stay null.
Neither summary is a substitute for checking actual execution and validation.

## Analysis and data definitions

`resource-summary.py` is a post-processing helper added after freeze. It only
reads existing records and writes grouped medians and non-success states; it is
not a workload runner. Its source and final hash are saved with the delivery.
`summary.csv` retains each run and its state. Conditional bootstrap intervals
in `paired-results.json` resample the observed successful same-block ratios
with seed 9505 and 10000 resamples. They do not include failed executions or
establish population-level confidence from five processes.

F16 reader and materialized inputs use the same deterministic values. The
materialized control's construction time is outside the merge API and recorded
separately. The R reader generates all 3000000 rows lazily; source epoch 1 adds
2^42 to every generated non-key field, whereas target values are below 2^40.
The validator streams every row and field. Wide payload contents use a separate
per-physical-row RNG seed and are checked by SHA256, with unique row_marker
values retained through duplicate-key updates.

`workloads.json` adds descriptive metadata after freeze without changing any
executed workload spec. Each run's original `spec.json`, the frozen bench.py
and initial fixture metadata determine the actual experiment. The V_sparse
physical fixture is V_sparse_r2. Its independent per-row length distribution
was corrected before freeze; the older arithmetic-cycle fixture was never
measured and remains preserved.

## Post-exit OOM cleanup recovery (harness h1)

The original frozen harness and checkpoint remain in `harness-r0/`. Dense Early
Ccore was killed at 8 GiB and saved its OOM events, then immediate cgroup removal
raised EBUSY. Preserve `logs/late-smoke.log`, the original partial metrics, raw
resource events, and `diagnostics/harness-h1-recovery.md`. The recovered terminal
state uses those saved events; the failed workload was never repeated. A separate
U check confirmed its latest manifest remained the pre-operation snapshot and
no source replacement was visible.

The read-only reviewer accepted the exact correction in
`diagnostics/review-h1.md`. Cleanup retries EBUSY for at most 5 seconds and records
its result separately. Before any worker starts, the coordinator refuses a
populated prior benchmark group. Six tests passed. The source and binaries did
not change. `freeze-h1.py` rehashed all four extensions, the test binary, source,
original documents, patch, and preserved original harness, then created the new
`freeze.json` with its original checkpoint as parent. Earlier r0 measurements
retain their provenance; later plans explicitly carry harness_revision=h1.

The completed checkpoint command, from C/python, was:

```sh
uv run --no-sync python /mnt/lance/validation-9505/results/20261018T103247Z-C-r2/diagnostics/cleanup-tests.py
uv run --no-sync python /mnt/lance/validation-9505/results/20261018T103247Z-C-r2/freeze-h1.py
```

The failed late-smoke stage must not be rerun from its start. Its first four cells
already passed and dense Early is a confirmed OOM. Only the unstarted dense Clate
cell was resumed, using `bench.run('Clate', bench.workload('W_dense'),
'g4-smoke-W_dense-Clate')` after checking the h1 hashes. It passed. The failure
and success cannot form a latency pair.

Core5 passed all 45 formal executions. `diagnostics/core3-decision.json` and
`diagnostics/core5-decision.json` record the pre-registered checks. Native was
far from its threshold, so blocks6–9 and Cbudget_late are not applicable. The
standard Ccore/Clate base is retained for the five Wn pairs. Single-run skew,
source-boundary and FirstSeen checks did not trigger further expansion.


## Final finite execution and delivery

The core45, boundaries, skew, FirstSeen, late-smoke, late5 and slow stages are
complete. Final low-memory measurement calls use exactly finite.py low's five
cells and order. They were invoked through finite.measured in a Python here-doc
so that an additional U snapshot/row-count check ran immediately after each OOM,
before the next variant restored that fixture. No workload or limit changed.
The five terminal IDs and outcomes are in logs/low.log. Failure checks are saved
as failure-snapshot-validation.json and failure_snapshot-resource-events.json.
Those checks do not turn a failure into a completed workload.

The slow stage completed all 16 cells. All four expected Pending cases reached
the producer Pending marker, were externally cancelled, and passed independent
unchanged-value checks. First-write timestamps were not observed by the selected
syscall filter; latency-results.json retains nulls. This is a remaining evidence
limit, not a zero-latency result.

Final post-processing commands, from C/python:

```sh
uv run --no-sync python /mnt/lance/validation-9505/results/20261018T103247Z-C-r2/summarize.py
uv run --no-sync python /mnt/lance/validation-9505/results/20261018T103247Z-C-r2/resource-summary.py
uv run --no-sync python /mnt/lance/validation-9505/results/20261018T103247Z-C-r2/latency.py
uv run --no-sync python /mnt/lance/validation-9505/results/20261018T103247Z-C-r2/write-report.py
```

The final report states the supported and failed claims. ARTIFACTS.sha256 covers
result files without traversing the fixture symlink. Preserve the fixture link
and its sibling data directory when moving this result set. For a fresh replay,
copy the harness into a new result root and generate/point to the recorded
fixtures; do not reuse completed run IDs or overwrite these results. Re-freeze
that new execution root and preserve its relation to this original evidence.


Exact additional Rust selections, after the optimized test binary exists:

```sh
export CARGO_TARGET_DIR=/mnt/lance/targets/C
LANCE_MERGE_EXPERIMENT=Clate LANCE_ENABLE_UNSTABLE_DATA_OVERLAY_FILES=1 /mnt/lance/targets/C/release-with-debug/deps/lance-31a368c8670aef12 spilled_lineage --test-threads=4
LANCE_MERGE_EXPERIMENT=Clate LANCE_ENABLE_UNSTABLE_DATA_OVERLAY_FILES=1 /mnt/lance/targets/C/release-with-debug/deps/lance-31a368c8670aef12 first_seen --test-threads=4
```

The final source patch passes `git apply --check --reverse C.patch` against the
unchanged C working tree, including its three new files. U/B/P worktrees remain
clean. Baseline setup and the original first-install command are retained in
`../20261018T092212Z-C-r1/RUNBOOK.md`; the environment handoff records the restored
U/P setup. B's optimized build log is retained in the sibling logs directory.
No historical latency sample is imported from those setup records.
