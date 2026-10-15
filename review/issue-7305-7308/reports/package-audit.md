# Independent evidence audit

Audit date: 2026-10-15 (UTC).

Candidate source: `09d2c8a0deff51d59b77a83f68d54fed2c277710`.

Comparison base: `08ea2c11674daf4791a00388b0bbe4bd9b339121`.

## Scope

A separate agent inspected the retained test logs, all six diagnostic records, and selected source paths at the candidate commit.
The audit checked report evidence and the boundaries of resource-control claims.
It did not rebuild the project, rerun tests, or perform a complete code review.

The working tree was clean when source inspection began.
The implementation diff contains 15 files, 4,001 insertions, and 386 deletions.
Later report-only changes do not change the candidate source revision.

## Verified evidence

| Evidence file | Verified result |
| --- | --- |
| `final-shuffler-tests.log` | 56 passed, zero failed. |
| `final-resource-tests.log` | Builder: 29; scheduler: 19; build/optimize: 2; fragment-reuse split/join: 2; failure atomicity: 2; legacy switch: 1. All passed. |
| `wide-input-tests.log` | Two fixed-vector/multivector append cases passed. |
| `storage-tests.log` | Two source-ownership cases passed. This earlier package build emitted unrelated throttle dead-code warnings. |
| `default-regressions.log` | PQ: 6; SQ: 4; RQ: 16; HNSW PQ: 8; HNSW SQ: 4; split/join: 1; NULL: 10; HNSW empty partition: 1; optimize empty partition: 1. All passed. |
| `clippy-final.log` | Cargo finished the dev profile successfully. The retained output contains the fp16/bf16 feature-disabled build-script notices. |
| `resource-diagnostic.jsonl` | Six complete JSON records, with consistent fixture dimensions and correctness checksums. |

The default regression log also contains an older one-case resource test and a filter that selected zero tests.
Neither should count as additional coverage.
Earlier builder and input-batching logs overlap the final resource run.

The retained files do not include raw output for the reported 19 spill tests or four metadata spill tests.
Those counts depend on the implementation transcript unless a later report supplies another retained log.
The formatting run has no retained raw log. The Clippy logs do not establish the full command line or source revision.
Command and run-order provenance must be identified as task execution records rather than information embedded in those logs.

## Diagnostic interpretation

Each record describes 262,144 Float32 vectors, 64 dimensions, 64 partitions, and input batches of 4,096 rows.
There are uniform and hotspot cases at unbounded, 8 MiB, and 32 MiB settings.
The hotspot fixture assigns half the rows to partition zero.

| Pool setting | Flush groups, both distributions | Peak reservation, bytes |
| --- | ---: | ---: |
| Unbounded control | 2 | 135,719,168 |
| 8 MiB | 32 | 4,541,824 |
| 32 MiB | 8 | 18,101,248 |

Every record reports zero final pool reservations, zero tracked live spill bytes, and zero tracked live spill files.
Every run created four tracked spill files.
All row-ID checksums equal 34,359,607,296.
All vector-bit checksums equal 17,662,399,169,384,832.

The source validates every row ID, partition assignment, and vector value before printing a successful record.
It detects duplicate row IDs and verifies the total row count.
The diagnostic therefore checks exact shuffle contents, beyond comparing aggregate checksums alone.

These are debug resource diagnostics, not optimized throughput measurements.
The unbounded setting is a control for the candidate implementation, not a historical baseline.
Write time includes data generation; read time includes exact verification.
The reader consumes full partitions directly and does not exercise the dataset partition-admission scheduler.
The six records do not establish end-to-end IVF build speed, query recall, or behavior under concurrent builds.

Peak reservations are accounting values, not allocator measurements.
Process RSS includes memory outside the pool and may exceed the configured limit.
Spill metrics count accepted bytes and ownership lifetimes; they do not measure filesystem allocation blocks.

## Source scope checks

Selected source inspection supports these report boundaries:

- `CreateIndexBuilder::with_memory_pool` and `OptimizeOptions::with_memory_pool` accept caller-owned DataFusion pools.
- The current IVF factory supplies the Session spill store to shuffle data, offsets, and page-metadata writers.
- The finite shuffle target is half the pool limit. Supplied pools disable the shuffle writer's data cache.
- Failed admission can release optional offset caches before returning a minimum-working-set error.
- Partition admission reserves before starting materialization. Active jobs and held results retain permits.
- The legacy shuffler remains available without an explicit pool or custom Session store.
- Scalar builds reject this pool option. Scalar optimizations ignore it, as documented in `OptimizeOptions`.
- Public API documentation excludes model training, HNSW graphs, upstream scan buffers, and codec buffers from the accounting.

The branch must not be described as an RSS cap, arbitrary oversized-partition support, or an all-in-memory shuffle implementation.
This audit does not establish that every goal in the historical parent issues is complete.
Maintainer acceptance and full issue closure remain external decisions.

## Evidence limitations

The retained logs and JSON do not embed the source SHA.
Their association with the candidate comes from task execution history.
This audit independently confirms their contents and selected final source behavior, but does not recreate execution provenance.

No optimized baseline comparison or production-scale workload measurement was available.
This audit did not inspect every cancellation path, estimate formula, concurrent schedule, or file-format invariant.
Passing the listed tests does not prove those paths correct for all inputs.

## Package findings

The assembled delivery, design, baseline, validation, resource, review-history, and PR-draft reports were checked against the evidence described above.
No actionable mismatch was found in their numerical claims or documented source scope.
The reports distinguish transcript-reported checks from retained output, and earlier runs from final affected-test runs.
They preserve the limitations on RSS, optimized performance, source provenance, and historical issue closure.

All twelve original evidence files were independently compared byte-for-byte with the packaged copies and matched.
All existing local Markdown targets resolve.
At this check, the audit file and publication manifest were still awaiting insertion; their four incoming links were the only unresolved targets.
The publisher must run the bundle verifier after inserting those two files and generating final hashes.

The verifier script was inspected. It checks the published file set, file sizes and hashes, local targets, candidate source bytes, and six diagnostic records.
It does not authenticate historical execution provenance, consistent with its output and the report warnings.
The environment snapshot explicitly identifies itself as packaging-time information, not a historical build attestation.

This conclusion applies to the reviewed report files before their publication commit.
It is evidence-package validation, not approval to merge the implementation.
