# Lance staged segment coverage

The local patch restores valid staged coverage after v0 deferred compaction.
The reproduced baseline returned correct rows but scanned every compacted fragment.
The patch keeps the index on the selective lookup path.

The baseline is upstream main at `fc5cb646e647e0cdd497fa1cf8ce0c6f25abeb75`.
GitHub still reported that SHA before measurement.
The patch branch is `fix/10096-staged-v0-coverage` in [worktree](worktree).
The original working branch and its existing changes remain intact.
No local commit or GitHub publication accompanies this delivery.

## Independent verification

[Issue 10096](https://github.com/lance-format/lance/issues/10096) remains open.
The final regression uses supported APIs to stage real BTree files, compact data, and publish from a newly opened dataset.
It compares actual `id` and `val` rows with an index-disabled query.
It also checks coverage, the build version, and executed `rows_scanned` counters.

The main baseline passes the two pinned-publication controls.
It fails both publication-from-latest cases because valid live coverage becomes empty.
The untouched case expects both compacted fragments.
The updated case expects only the unaffected compacted fragment.
The final patch passes both cases and their controls.

Related work does not close this gap:

| Change | Checked state and scope |
|---|---|
| [10090](https://github.com/lance-format/lance/pull/10090) | Open draft. Documents coverage and version semantics. It changes no runtime behavior. |
| [9808](https://github.com/lance-format/lance/pull/9808) | Merged. Handles concurrent CreateIndex rebasing from an older read snapshot. |
| [9271](https://github.com/lance-format/lance/pull/9271) | Open at `bc389485c165ede98d71eb8ea9530aba862d6760`. Changes segment merging, not direct publication. |
| [9947](https://github.com/lance-format/lance/pull/9947) | Open at `49fa1cf69cd973a3f698b155b4d62c7882c55add`. Checks missing history after the existing pruning pass. |

## Design and tradeoffs

Address translation alone cannot prove that an index still contains current values.
The patch reuses `fresh_fragments` to compare indexed files, overlays, and row revival through the required rewrite snapshots.
Missing required snapshots or rewrite transactions withdraw the affected coverage.

The new reverse walk retains original source IDs only when every destination of their rewrite group remains covered and fresh.
The stored bitmap and `dataset_version` keep their original meanings.
Readers still translate the stored row addresses through the FRI.
A concurrent history cleanup can therefore remove translation without leaving a false claim on current fragments.
Those rows return to the scan path.

Replacement decisions use a separate, normalized live bitmap.
This prevents an incoming old-ID segment from appearing disjoint from an existing segment that covers the same current fragments.
The existing orphan-coverage rejection remains effective.

The shared conflict check now recognizes a packed parent as a dependency of an indexed child.
It rejects a racing DataReplacement through the existing retryable conflict path.
The patch adds no persistent metadata, file-format change, or public API change.

The retention gate includes native physical IDs on tables without stable row IDs.
It preserves the existing NGram rejection and FM fallback.
JSON wrappers keep their existing fallback because their targets can ignore FRI translation, including wrapped FM.

The checks are conservative.
A stale destination can withdraw other destinations in the same rewrite group.
Independent segments that split one group still need a merge before they can claim that group's output.
Rewritten files can also trigger fallback when their values happen to remain equal.

## Tests and review

All Rust compilation, tests, and benchmark execution ran on ECS through the documented environment, locks, and tmux workflow.
All edits and formatting ran locally.
Each long phase retains its command, source snapshot, log, and exit code under [results](results).

| Final check | Result |
|---|---|
| `dataset::optimize::tests::concurrent_reindex` | 45 passed |
| `index::` filter | 1591 passed, 1 existing child-process helper ignored |
| `io::commit::conflict_resolver` | 146 passed |
| `cargo clippy --all --tests --benches -- -D warnings` | Passed |
| Manual benchmark Clippy with default features | Passed, with its expected stderr output explicitly permitted |
| `cargo fmt --all -- --check` and `git diff --check` | Passed |

The broader index run includes the 45 focused cases. These counts are not additive.
The ignored helper runs as a child of its parent test.
New cases cover unchanged values, unrelated updates, indexed updates, folded overlays, missing history, chained compaction, partial groups, retries, and replacement boundaries.
The IVF-flat case checks recall and exact neighbors against an index-disabled scan.
The FM and JSON/FM cases require scan fallback.

The independent source review found no remaining P1 issue after corrections.
An independent benchmark audit checked sample counts, query pairing, source configuration, and reported medians.
See [review notes](REVIEW.md).

Intermediate failures remain in the bundle.
They include the baseline reproduction, an initial benchmark closure error, a narrow identifier-domain gate, and an incorrect history-test target.
The corrected versions pass.
Extra benchmark lint attempts also exposed existing no-default-feature dead code and expected stderr output.
The required workspace lint and the final scoped benchmark lint pass.

## Measured results

The workload contains 4,000,000 rows and two Int64 columns.
One fixture supplies byte-identical copies for baseline and patched publication.
Compaction changes 16 fragments into 8 fragments.
Coverage changes from 0/8 to 8/8 live fragments while the build version remains 2.

Both binaries use `release-with-debug`, the same compiler pin, lockfile, Cargo configuration, and benchmark source.
The host reports AMD EPYC 9T25, 16 vCPUs, and 61 GiB RAM.
The script holds the exclusive host lock and records process inventories.
The measurement completes with exit code 0.

Every invocation first warms OS pages with the same index-disabled scan.
Five rounds alternate execution order.
Each cache mode contains 100 timed queries per variant after five warmups per invocation.
All 500 queries, including warmups, check their returned `id` and `val`.

| Warm OS pages | Baseline median | Patch median | Baseline / patch | Baseline p95 | Patch p95 |
|---|---:|---:|---:|---:|---:|
| Fresh Lance session | 5.8875 ms | 0.8005 ms | 7.35× | 6.022 ms | 0.868 ms |
| Reused Lance session | 5.6160 ms | 0.5185 ms | 10.83× | 5.790 ms | 0.616 ms |

All five round medians favor the patch.
Their ratios range from 7.17–7.51× for fresh sessions and 10.54–11.08× for reused sessions.

| Metric per query | Baseline | Patch |
|---|---:|---:|
| Executed `rows_scanned`, every sample | 4,000,000 | 1 |
| Storage API bytes, fresh-session median | 25,791,552 B | 78,524 B |
| Storage API bytes, reused-session median | 25,727,488 B | 41,120 B |

Analyzed plans show the baseline scanning all eight fragments.
The patch uses ScalarIndexQuery and reads one selected data row.
These counters establish the mechanism independently of the latency result.

The query timer includes construction, planning, and execution.
It excludes dataset opening, fixture creation, publication, and initial cache warming.
Storage API bytes include cached reads. They do not measure physical disk traffic.
Plan-byte counters cover a narrower scope and omit some index-loading traffic.

The single publication samples are 1186 µs and 1266 µs.
They cannot establish a commit-latency change.
The process inventories show no competing build or test at the recorded boundaries.
They do not provide continuous host monitoring.

Exact commands are in [REPRODUCE.md](REPRODUCE.md), [run.sh](run.sh), and [measure.sh](measure.sh).
Raw samples and analyzed plans are in [measurement](results/measurement).
The [summary](benchmark-summary.json) records distributions and round medians.
The fixture and publication metadata archives permit repetition without regenerating input data.

## Remaining limits and usable evidence

The measured gain applies to selective local BTree equality queries with warm OS pages.
It does not establish cold-storage, object-storage, vector-performance, or application-wide gains.
The vector test proves correctness and coverage, not speed.
No full-workspace test execution or Python test session ran.
No Python or Java source changed.

JSON wrappers remain on the existing fallback path.
The patch does not solve arbitrary saved metadata that already names post-build fragments.
That case includes the eager-remap ambiguity in PR #9947.
Custom plugins that ignore FRI translation remain outside the tested scope.

The evidence supports an interview discussion about diagnosis, value validity, provenance, retries, and measured query behavior.
It also supports a resume statement that identifies this as a proposed and locally tested Lance change.
The quantified statement must retain the 4M-row BTree workload and warm-cache boundary.
It must not claim upstream acceptance, production deployment, or a general Lance speedup.

The bundle retains logs, source archives, raw samples, fixture data, and publication metadata.
Binary checksums identify the measured executables.
Rebuildable executables and duplicate uncompressed datasets remain outside the local bundle.
The integrity record verifies every copied result against its remote SHA256.

The production worktree contains three modified Rust files.
The manual benchmark harness remains at [staged_coverage_bench.rs](staged_coverage_bench.rs), outside the proposed PR diff.
Build snapshots retain its temporary copy under `rust/lance/examples`.
The tracked local diff matches the compiled snapshot.

The final copy check covers 259 files and 553,728,822 bytes.
All SHA256 values match [the remote manifest](remote-sha256.json).
See [the integrity record](integrity-check.json) and [check command](check-results.py).

The final host audit obtained both exclusive locks and found no remaining work task.
Only the earlier environment verification's passive log viewer remained, with its completed task exit code of 0.
After result recovery, the local `lance-ecs-stop` command completed with `Stopped + StopCharging`.
See [the audit](shutdown-audit.txt) and [shutdown log](shutdown.log).
