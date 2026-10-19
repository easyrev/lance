# Unified merge experiments

This runner compares actual imported extension and source hashes. U, B, P, D,
CTX, DB and DP are labels, not evidence of code identity. Every candidate is
based on `0a0d327082988018a25f56147d3b6d02f6c79ecc`. Existing D is the final,
selector-free implementation preserved in commit `50e216972e1558ce253bece5db462d8241fde96a`.

Only the parent agent runs SSH, builds or experiments. This harness was prepared
locally without running Python or a benchmark. Follow `python/AGENTS.md`: each
checkout first completes `make install`, then the optimized extension build.
Run Python through its existing `uv run --no-sync` environment. Keep compilation
out of performance runs; `no_builds` checks each cell's entry, and the parent
owns scheduling throughout execution. Fixture generation may overlap compilation
and records that fact. It contributes no timing samples.

## Prepare and freeze

Copy this entire harness directory to
`/mnt/lance/unified-9505-20261019/harness`. Keep prior evidence immutable.
The result root and imported fixtures must share a filesystem for hard links.
The local mirrors have no dataset files; import from the original remote roots.
The root agent has confirmed the build-log paths in `config.example.json`.
The pool descriptions reflect the parent agent's source review, including DP's
shared execute/analyze contexts. Actual reservation peaks are not currently observed.

The cgroup v2 root is exempt from the no-internal-process rule. The dedicated
experiment parent must be empty before enabling controllers; keep the
coordinator outside it. Missing control files are a hard error. Never create
ordinary files as substitutes for cgroup controls.

```sh
set -eu
source /mnt/lance/env.sh
cd /mnt/lance/checkouts/U_main/python
unified_root=/mnt/lance/unified-9505-20261019
unified_harness="$unified_root/harness/harness.py"
test "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs
printf '+cpu +memory\n' > /sys/fs/cgroup/cgroup.subtree_control
mkdir /sys/fs/cgroup/lance-unified-9505
test -z "$(cat /sys/fs/cgroup/lance-unified-9505/cgroup.procs)"
printf '+cpu +memory\n' > /sys/fs/cgroup/lance-unified-9505/cgroup.subtree_control
mkdir /sys/fs/cgroup/lance-unified-9505/preflight
test -f /sys/fs/cgroup/lance-unified-9505/preflight/memory.max
test -f /sys/fs/cgroup/lance-unified-9505/preflight/memory.swap.max
test -f /sys/fs/cgroup/lance-unified-9505/preflight/memory.oom.group
test -f /sys/fs/cgroup/lance-unified-9505/preflight/cgroup.kill
test -f /sys/fs/cgroup/lance-unified-9505/preflight/cpu.max
rmdir /sys/fs/cgroup/lance-unified-9505/preflight
uv run --no-sync python -m py_compile "$unified_harness" \
  "$unified_root/harness/fixtures.py" "$unified_root/harness/legacy_fixtures.py"
uv run --no-sync python "$unified_harness" init --config "$unified_root/harness/config.example.json"
uv run --no-sync python "$unified_harness" freeze --name fixtures --variants U
```

Freeze records the selected variants only, always including validator U. It
captures full tracked/untracked Rust and Python source hashes, actual imported
module and extension identities, Python/PyArrow versions, build-log hashes,
runtime environment, code/workload definitions and machine identity. It can
freeze U while other variants build. Later freezes include newly ready labels.
Selected entries and harness code must stay unchanged; extending an unselected
variant entry does not invalidate the U-only freeze.

## Reuse and generate fixtures

Import validates the old generator against its freeze, exact workload spec,
every file name/hash, metadata, snapshot, row count and fragment count. Immutable
`.lance` files are hard-linked; metadata is copied. Each plan embeds the complete
selected fixture manifests, and run entry checks them again. Generated fixture
provenance records its generator's frozen identity and environment.

```sh
uv run --no-sync python "$unified_harness" import-fixtures \
  --source-root /mnt/lance/killer-merge-20261018 \
  --workloads tiny,string_null,condition_overlap,condition_reject,F16,Wn,Ws,dense_safe,R
uv run --no-sync python "$unified_harness" import-fixtures \
  --source-root /mnt/lance/killer-merge-admission-fixed-20261019 --workloads R_admission
uv run --no-sync python "$unified_harness" generate --freeze fixtures \
  --workloads N_dense,V_dense,late_jump,F64
```

The historical F16 baseline OOM remains background evidence. This run performs
one fresh U/F16 survival cell under the new measurement protocol and 8 GiB cgroup.
A confirmed failure is preserved and independently checked; subsequent matching
cells reference that new failure without rerunning it. References never become
timing samples, successful gates, speedups or variance observations.

## Minimal decision sequence

Start with ready candidates only. All non-correctness plans require four small
correctness cells for every selected identity. Every cell uses a fresh process,
dataset directory, cgroup and operation-specific TMPDIR. Successful execution
requires full source consumption, worker identity and an independent U oracle
checking every field, row, action count and latest dataset version. Failure
oracle reopens the latest version and checks all original values against a
coordinator-written initial snapshot, even if the worker never wrote metrics.
The validator's actual imported identity must equal frozen U.

Survival preserves and continues past confirmed OOM/resource exhaustion for any
variant only when its unchanged oracle passes. Timeouts, infrastructure errors,
internal execution errors, source errors and value mismatches stop. Resource
failure is a boundary finding, not a successful gate. A repeated matching
resource failure produces a reference. Pairs only accept contracts with a
previous successful survival/cold result; any pair failure stops the plan.

```sh
# Wait for the selected builds and required tests to finish first.
uv run --no-sync python "$unified_harness" freeze --name initial --variants U,CTX,D,B,P
uv run --no-sync python "$unified_harness" make-plan --name correctness-initial \
  --freeze initial --kind correctness --variants U,CTX,D,B,P
uv run --no-sync python "$unified_harness" run correctness-initial
uv run --no-sync python "$unified_harness" make-plan --name survival-initial \
  --freeze initial --kind survival --variants U,CTX,D,B,P --workloads F16,Wn,Ws
uv run --no-sync python "$unified_harness" run survival-initial
uv run --no-sync python "$unified_harness" make-plan --name reverse-initial \
  --freeze initial --kind survival --variants U,CTX,D,B,P --workloads R_admission --pool-mib 256
uv run --no-sync python "$unified_harness" run reverse-initial
```

Inspect each gate before selecting more cells. Test N_dense, V_dense and
late_jump first with CTX and D. Add B/P or DB/DP where warm observations can
change the decision. Test F64 with two promising identities before expanding.
F64 isolates target key/address cardinality growth: it has the same 44 int64
columns and 100 source rows as F16, with 64 million target rows. N_dense is
200,000 unique-key rows with eight int64 columns and 180,000 updates. V_dense is
100,000 unique-key rows, 90,000 updates, ordinary Utf8/LargeBinary omitted fields
of 128–2048 bytes, deterministic NULLs, and shuffled source keys. They test high
coverage without a few repeated target keys; dense_safe separately covers
duplicate target keys.

late_jump has one source batch of 1,024 ascending keys; target omitted binary
values are 32 bytes for 64 rows, then 1 MiB for 960 rows. Target storage/source
order does not prove join-output or materializer order. Use runtime diagnostics
or a targeted unit test before claiming that a particular chunk saw small then
large values. P/DP whole-table scan sizing can split the target stream first,
which is a separate cause of reduced pressure.

```sh
uv run --no-sync python "$unified_harness" make-plan --name ordinary-survival \
  --freeze initial --kind survival --variants CTX,D --workloads N_dense,V_dense,late_jump
uv run --no-sync python "$unified_harness" run ordinary-survival
# Example only: both contracts must have successful survival results.
uv run --no-sync python "$unified_harness" make-plan --name ordinary-pairs \
  --freeze initial --kind pairs --variants CTX,D --workloads N_dense,V_dense \
  --comparisons D/rewrite_rows:CTX/rewrite_rows
uv run --no-sync python "$unified_harness" run ordinary-pairs
```

Pairs use three blocks, fixed random seed 950519 and randomized candidate order
within each workload/block. Explicit `--comparisons numerator:denominator`
registers the comparisons before execution. Adjacent mechanism comparisons are
U/CTX, CTX/D, B/DB, P/DP and D/DB or D/DP when useful. Compare writer modes only
where both survive; `--modes rewrite_rows,rewrite_columns` is an explicit writer
cross-product, not evidence that deferred payload alone caused the difference.
Register DB/DP in a new freeze when ready, run their small correctness gate,
then selected survival cells. Materialized source uses `--input-form materialized`
and requires its own survival evidence; its construction time is recorded
separately from the API boundary. Unknown-reader and known-materialized source
are separate contracts.

## Cold attempt and real-plan diagnostics

After warm results, choose one N_dense or V_dense comparison most likely to
change the early/late decision. A cold plan runs one block for the selected
variants. `evict_attempt` calls fsync and fadvise(DONTNEED) on the clone's original
data files, with per-file mincore snapshots before/after. This is advisory and
sequential: snapshots do not establish simultaneous residency of all files.
Actual execute read_bytes is separate evidence. Shared hard links change cache
state for their other aliases, so run sequentially. Never use global drop_caches.
If the decision changes, register three pairs with the same evict_attempt cache
contract; only previously successful cold contracts qualify.

```sh
uv run --no-sync python "$unified_harness" make-plan --name variable-cold \
  --freeze initial --kind cold --variants CTX,D --workloads V_dense --cache evict_attempt
uv run --no-sync python "$unified_harness" run variable-cold
uv run --no-sync python "$unified_harness" make-plan --name variable-cold-pairs \
  --freeze initial --kind pairs --variants CTX,D --workloads V_dense --cache evict_attempt \
  --comparisons D/rewrite_rows:CTX/rewrite_rows
uv run --no-sync python "$unified_harness" run variable-cold-pairs
# Requires an already successful matching survival contract.
uv run --no-sync python "$unified_harness" make-plan --name f16-d-plan \
  --freeze initial --kind diagnose --variants D --workloads F16
uv run --no-sync python "$unified_harness" run f16-d-plan
uv run --no-sync python "$unified_harness" summarize
```

Diagnose invokes `builder.analyze_plan(real_source)` on an independent clone
with the same input, writer and resource settings, preserves analyzed-plan.txt,
producer logs, IO and identity, and then runs an unchanged oracle. Analyze can
write uncommitted files. Its output goes under diagnostics and never enters
execute timing comparisons. P analyzes with a different context from execute;
record that limitation when interpreting its plan. Schema-only explain cannot
prove B's post-EOF selection. Do not analyze an already failing candidate at
the same cap; use static/explain evidence and mark the runtime gap.

## Measurement and audit contract

The sole performance timer surrounds `builder.execute(source)`, including
planning, lazy source generation, target scan, join, materialization, writer and
commit. Setup, cloning, cache preparation, validation and materialized-source
construction are outside it. Source rows/batches/Arrow bytes are recorded;
yield counts do not claim EOF polls or downstream memory retention. The runner
preserves raw errors and incomplete producer records on failure.

Record configured pool and source-reviewed effective policy separately from
process RSS and cgroup usage. U is unbounded at execution; B has separate
bounded contexts; shared-context variants still have allocations outside pool
accounting. No reservation maximum is inferred. Samples include per-process
VmRSS/VmHWM, cgroup memory.peak and memory.stat anon/file/shmem. Worker metrics
include VmRSS/VmHWM and ru_maxrss before/after the API. Shared hardlink pages may
remain charged to an earlier cgroup, so cgroup peak is not total RSS. Sampling
can miss short peaks. TMPDIR samples count live file sizes/allocated bytes and
files, plus the final file list. They are not cumulative spill writes and can
miss already-unlinked files. Process IO is cumulative over the API boundary.
New .lance bytes/count describe output files, not total device IO or lifetime
write amplification. The independent oracle runs after timing.

Audit exact planned/run/reference sets, all oracle identities and full-field
checks, source consumption, gate statuses and unchanged oracles. Recompute
latency/RSS/cgroup/new-file distributions from successful actual samples only.
Recompute each ratio within the same workload, plan and block, then take the
median of the three ratios. Do not divide independent medians, count inherited
OOM references as samples, or assign failed samples zero/infinite latency.
Retain failures and report non-advantages and unobserved mechanisms.
