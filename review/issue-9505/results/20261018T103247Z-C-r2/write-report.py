"""Render the final report from preserved measurements and decisions."""
import json
from pathlib import Path

R = Path(__file__).resolve().parent
pairs = json.loads((R / 'paired-results.json').read_text())
resources = json.loads((R / 'resource-summary.json').read_text())
counts = json.loads((R / 'status-counts.json').read_text())
assert counts['total'] == 108
pair_lines = []
for p in pairs:
    lo, hi = p['ratio_range']
    ci = p['bootstrap_95_percent_conditional']
    pair_lines.append(f"| {p['workload']} / {p['source']} | {p['candidate']} / {p['control']} | {p['valid_pairs']}/5 | {p['median_ratio']:.3f} | {lo:.3f}–{hi:.3f} | {ci[0]:.3f}–{ci[1]:.3f} |")
mem_lines = []
for variant in ['B', 'P_reconstructed', 'Cprep', 'Cbudget', 'Ccore']:
    g = next(g for g in resources['groups'] if g['formal'] and g['workload']=='F16' and g['source']=='reader' and g['variant']==variant)
    m = g['successful_medians']
    mem_lines.append(f"| {variant} | {m['merge_seconds']:.3f} | {m['cpu_seconds']:.3f} | {m['sampled_peak_rss_bytes']/2**20:.1f} | {m['sampled_peak_anon_bytes']/2**20:.1f} | {m['cgroup_peak_bytes']/2**20:.1f} |")
text = '''# Lance #9505 candidate C-r2: completed validation

Keep the guarded native mechanism for the measured F16 workload. Its five paired
ratios against Cbudget have median **0.318**, a **68.2% reduction in merge time**,
with all five ratios below one. Forced Late also merits retention as an internal
mode: Wn has median Late/Early ratio **0.274**, a **72.6% reduction**. Automatic
Early/Late selection remains unverified.

The candidate does **not** pass a blanket memory-safety claim. Early Ccore OOMed
on W_dense at an 8 GiB cgroup limit and on Wn/Ws at 2 GiB. These are valid negative
results. Late passed those distinct cells, but cannot erase the Early failures.
No failed cell was repeated and no resource limit or acceptance threshold changed.

All applicable registered experiments are complete. The main runner contains
**108 runs: 99 validated successes, two resource-exhaustion failures, three
confirmed OOMs, and four expected external cancellations**. All **55 formal
runs passed**, yielding five valid pairs for each reported comparison. The
remaining 53 runs are mechanism, boundary, pressure, or latency diagnostics;
they are not extra formal samples. Separate unit, semantic and pool checks are
listed below. See [summary.csv](summary.csv), [paired-results.json](paired-results.json),
[status-counts.json](status-counts.json), and the append-only [run manifest](run-manifest.jsonl).

## Provenance and execution

Implementation: `/mnt/lance/checkouts/C`, base
`dc53d5d174af62c49ddd98d1024a64488c1e4404`, plus the reviewed [C.patch](C.patch).
The patch includes all nine changed/new files; [C-source.tar.gz](C-source.tar.gz)
contains their frozen contents. No PR or upstream comment was created.

| Variant | Frozen commit |
| --- | --- |
| U | `dc53d5d174af62c49ddd98d1024a64488c1e4404` |
| B | `793e4e27119540a17ae37ce78d4f5f4d52060a93` |
| P_reconstructed | `90d981870c960e3bb55bfa46b206853ea4282fdb` |
| C-r2 | U plus reviewed frozen patch |

P_reconstructed is not verified equivalent to the unavailable historical P merge.
Its engineering comparison includes its optimizer/context changes; it is not a
pure shuffle ablation. U retains its unbounded pool on this path. Setting a
nominal quota for U does not make it a controlled pool baseline.

Builds use Rust 1.98.1, the repository `release-with-debug` profile and the same
haswell/AVX2/FMA/F16C flags. Actual imported extension paths, versions and SHA256
hashes are in [freeze.json](freeze.json). The host has 16 logical CPUs, 8 physical
cores, no swap, local NVMe/ext4, and no worker CPU quota. Frequency controls are
not exposed. Rust uses the default System allocator; PyArrow 25.0.1 reports
mimalloc. See [environment.json](environment.json).

Each operation uses a new child cgroup; the coordinator remains outside. Normal
cells use a 1 GiB DF pool and 8 GiB cgroup; R uses a 16 GiB cgroup. Source
construction for materialized controls, fixture restore, initial-file warming,
and independent U readback are outside the API timer. All API times include
preparation, planning, source consumption, writing and commit. Python reader workloads generate batches on demand. The separate Rust
FirstSeen mechanism fixture constructs two ordered batches before its API call. R's epoch changes every non-key source value; all rows and
fields are checked. Binary validation checks content hashes and unique physical
row markers. No compilation ran during measurements.

C-r1 was rejected for changing schema-error precedence. Its failure and review
remain in `../20261018T092212Z-C-r1`; none of its performance evidence is used.
The final C-r2 [read-only review](diagnostics/review-r2.md) cleared source and
harness before freezing and Gate 2.

A later post-OOM cgroup-removal race required harness h1. Original raw OOM events
were saved before EBUSY; the existing dense failure was recovered without
re-execution. [The h1 review](diagnostics/review-h1.md) accepted a bounded cleanup
retry and a guard against overlapping populated groups. The original harness
and freeze remain in [harness-r0](harness-r0/). The h1 checkpoint reverified all
four binaries and unchanged source. Earlier valid timings remain attributable
to r0; later plans identify h1. The correction executes outside the merge timer.

## Gate decisions

| Gate | Decision and evidence |
| --- | --- |
| 0: environment, identity, isolation | Passed. Separate worktrees, optimized imported binaries, hashes and cgroup limits verified. |
| 1: semantics and mechanisms | Passed for the implemented guarded scope. Rust/Python checks, strict Early/Late semantics, optimizer and pool diagnostics passed. |
| 2: real mechanism smokes | Passed required C completion/mechanism checks. 17/18 cells validated; P_reconstructed R exhausted its pool. |
| 3: core paired comparisons | Passed native retention. All 45 core runs validated. No registered stable regression or memory-investigation trigger. |
| 4: Late and memory boundaries | Late semantics/path and sparse performance passed. Fixed low-memory F4 passed. Early wide controlled-memory claim **failed** with three OOMs. |
| Slow-source diagnostics | Completed all four schedules for U/B/P_reconstructed/Ccore. Four Pending cases required external cancellation and left data unchanged. Some trace milestones remain unobserved. |

The optimized test selections passed: 357 merge tests, nine `native_` tests
(including three existing unrelated index tests), 23 forced-Late lineage tests,
and 21 forced-Late FirstSeen tests. These selections overlap and must not be
summed as unique tests. Python merge regression passed 38 tests. The separate
strict semantic harness passed 12 cases, asserting the actual Late path and
Take counts. Three pool diagnostics proved bounded failure at HashJoinInput,
unbounded completion with identical policy parameters, and bounded small-input
success. Formatting and lance-crate Clippy with tests/benches and warnings denied
passed; this was not a workspace-wide Clippy run.

The Rust test binary predates exactly two visibility-only lint corrections.
The reviewer accepted that exception; its hash and exact delta are preserved.
The final Python extension includes the corrections. Build failures and recovery
logs remain intact. The final make build needed a timestamp-only lance_arrow
cache recovery and then succeeded. [RUNBOOK.md](RUNBOOK.md) gives commands and
scope; the original design, brief and handoff hashes remain unchanged.

## Formal comparisons

Ratios are candidate/control API time within the same randomized block. Lower is
faster. Each comparison has five planned, completed, independently validated pairs.
Intervals resample the five observed successful ratios with seed 9505 and 10000
resamples; they are conditional descriptive intervals, not precise population
confidence claims. All individual ratios and times remain in paired-results.json.

| Workload / source | Candidate / control | Valid pairs | Median ratio | Range | Conditional bootstrap 95% |
| --- | --- | --- | --- | --- | --- |
''' + '\n'.join(pair_lines) + '''

Native's range is far from the 0.90 retention boundary, so expansion to nine
blocks was not applicable. The conditional Cbudget+Late branch was also not
applicable. Materialized input did not regress. R has a 3.5% median slowdown
against B; individual ratios range from 0.965 to 1.119, so the registered stable
>10% regression condition did not trigger. No result from another workload was
used to average away a regression.

Successful F16 reader medians, with memory shown in MiB (2^20 bytes):

| Variant | API seconds | CPU seconds | Sampled RSS MiB | Sampled anonymous MiB | Cgroup peak MiB |
| --- | --- | --- | --- | --- | --- |
''' + '\n'.join(mem_lines) + '''

Adjacent Cbudget/Cprep and Ccore/Cbudget memory changes did not trigger the
registered >10% plus >32 MiB investigation threshold. Ccore's observed F16 pool
peak was 4696 bytes; that only covers tracked reservations. RSS samples select
the largest resident process, not a sum. Cgroup memory covers the group and
charged cache; shared library/file pages can be charged elsewhere. These metrics
are not interchangeable. Raw integer bytes are retained in every metrics file.

## Mechanism evidence and boundaries

F4 Cbudget/Ccore use the same policy size, effective P=14, decode-task limit=14,
width=396 and 256 MiB I/O setting. Ccore has 14 scan outputs with no scan-boundary
RoundRobin; Cbudget has one output plus RoundRobin. Each initializes one scan
and builds 100 source rows once. Shared task/drop tests cover Pending work,
worker errors, cancellation and fresh reset state. Global row statistics stay
Exact while individual dynamic partition row counts are Inexact. Reduced-P tests cover P=2
and P=1 without expansion back to 16. See [Gate 2 evidence](diagnostics/gate2-mechanisms.json).

R preparation stops at 163840 rows, retaining the whole crossing batch. Its
small-fixed-target decision uses the actual narrow target projection. Normal
optimization produces a partitioned target build, updating 100000 rows and
inserting 2900000. No forced final join mode or optimizer disabling was needed.
The Auto counterexample retains a 262144624-byte first batch without EOF. Its
variable target projection exposes both rows and bytes as Absent; the final
plan uses a partitioned source build. Allocation-free tests cover the unsafe
bytes-only counterfactual with the statistics registry on and off.

Boundary smokes confirm EOF at 100000 source rows and Prefix at 1000000; C
completed both. B's one-million-row cell exhausted HashJoinInput. F4 skew and
FirstSeen passed without an expansion trigger. FirstSeen uses the Rust test
binary because the Python builder has no setter: 200 input rows yield 100 first
winners and 100 skipped duplicates. It is not a Rust/Python latency comparison.

Wide Ccore mode does not always mean native multi-output execution. Wn/Ws/Wauto
retain one actual scan output; their detailed plans record one initialization
and the existing shared scheduler. Cprep logs derived policy parameters but
leaves its old scan row/I/O settings unapplied; Cbudget applies them. Do not
mistake a derived resource log for an applied scanner setting.

Forced Late prunes old payload columns from the join scan, then Takes only
actual UpdateAll physical addresses from the same snapshot. V_sparse Takes 25
rows (39979 returned Arrow bytes); Wn Takes 25 (131072952 bytes). All five formal
Wn Late runs report 25 Takes. The V_sparse smoke was 2.037 seconds Early versus
0.028 seconds Late, with full two-million-row readback. This is a single smoke,
not a repeated effect estimate. Its corrected independent length generator was
frozen before any V_sparse measurement; the old arithmetic-cycle fixture was
never measured.

W_dense has unique row_marker values and repeated hot keys across fragments.
Early OOMed at 8 GiB. Late validated 360 physical updates, Took 1887445792 Arrow
bytes, ran for 8.790 seconds and peaked at 7184232448 cgroup bytes (6.69 GiB).
There is no valid dense latency ratio against failed Early. The failed Early
manifest remained unchanged. High physical coverage still creates substantial
Late Take/write residency; a small count of source keys does not imply sparse
physical updates.

The fixed low-memory Ccore F4 cell passed in 0.147 seconds with a 256 MiB pool
and 2 GiB cgroup. Wn/Ws Early both hit confirmed OOM at 2 GiB. Their manifests
and row counts remained unchanged. Distinct Late cells both validated: Wn peaked
at 625291264 cgroup bytes; Ws at 1941757952 bytes (1.81 GiB). See
[low-memory-decision.json](diagnostics/low-memory-decision.json). These successes
establish those cells only, not an arbitrary-workload hard bound.

## Producer latency and remaining limits

The first-batch and later-batch 250 ms delays are included in API times. Ccore
spent about 253 ms in preparation and completed in about 298–300 ms; B/U/
P_reconstructed completed in about 271–273 ms under the diagnostic trace.
These single tiny traced cases do not establish a stable performance regression.
At the 1024-empty-batch boundary C stopped preparation on the batch cap and
completed. All four permanently Pending producers reached Pending, required the
external 3-second timeout, and passed independent unchanged-data checks.
There is no wall-clock preparation deadline and no guarantee of preemption for
a synchronous blocking Python producer.

[latency-results.json](latency-results.json) records producer readiness, observed
C planning completion, target reads and total API time. Planning completion is
unobserved for baseline binaries. Target reads include footer reads. The selected
read/pread64/write trace did not observe the first output-data write in any case;
that milestone is null, not inferred from file creation or completion. Full
first-write timing therefore remains unverified. Trace runs are excluded from
formal timing comparisons.

Keep bounded preparation, dual-Absent Guard, initial policy with normal Auto,
canonical bounded context, and the measured guarded native integration. Keep
Late as a guarded forced prototype for supported omitted fields. Do not enable
an automatic policy from these few workloads. Width-based decode/row/I/O budgets
remain soft estimates: whole source batches, storage pages, Take/output/writer
buffers and FirstSeen distinct-key state can exceed those estimates. Retry plans
refresh the snapshot, but soft sizing resources can retain an initial-snapshot
estimate. Unsupported blob/nested/order-sensitive paths retain their guards.

Payload counters measure Taken rows and returned Arrow memory. Aggregate scan
bytes exclude separate TakeBuilder storage I/O, so neither is total physical
storage traffic. No remote throughput, global admission, process-wide memory
bound, cold-cache, or F64 scaling claim is supported. Those optional expansions
were not triggered; no authorized remote endpoint was available.

Historical reports informed fixture selection only. All numerical results above
are new measurements. The keep/force recommendations are engineering inferences
from those measurements. Historical P equivalence, automatic Late selection,
complete physical Take I/O, first-write latency and untested scale/storage regimes
remain unverified.
'''
(R / 'REPORT.md').write_text(text)
print('wrote REPORT.md')
