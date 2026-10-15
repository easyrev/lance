# Baseline comparison and code map

Base: `08ea2c11674daf4791a00388b0bbe4bd9b339121`.
Candidate: `09d2c8a0deff51d59b77a83f68d54fed2c277710`.
This is a source comparison. No historical throughput baseline was measured for this task.

## Behavior comparison

| Area | Base | Candidate |
| --- | --- | --- |
| Caller memory control | Independent local limits on the IVF path | Optional caller-owned pool shared across supported build stages |
| Partition admission | Local byte and entry scheduling | Pool reservation before materialization, retained through result ownership |
| Shuffle scratch | Temporary storage outside Session spill accounting | Data, offsets, and metadata scratch through the Session spill store |
| Optional offsets | Read optimization with its own size policy | Pool-accounted cache with pressure-driven eviction and disk fallback |
| Oversized work with no explicit pool | Existing exclusive-job behavior | Preserved |
| Oversized work with an explicit pool | No such caller-owned IVF contract | Return a resource error if the minimum admitted working set cannot fit |
| Completed partition persistence | Direct writes to final index files | Same persistence architecture |
| Full process RSS | No complete cap | Still no complete cap |

## Code map

All links below point to source files in this branch. The manifest records their hashes at the code candidate.

| File | Review focus |
| --- | --- |
| [spill.rs](../../../rust/lance-io/src/spill.rs) | Accepted-byte quota accounting, shared file ownership, cancellation, and shutdown |
| [structural.rs](../../../rust/lance-file/src/writer/structural.rs) | Page-metadata scratch through SpillStore |
| [v2_1/writer.rs](../../../rust/lance-file/src/versions/v2_1/writer.rs) | Forward spill resources into structural writing |
| [shuffler.rs](../../../rust/lance-index/src/vector/v3/shuffler.rs) | Pool reservations, flushing, cache eviction, file and reader lifetime |
| [storage.rs](../../../rust/lance-index/src/vector/storage.rs) | Release source batches before storage conversion |
| [optimize.rs](../../../rust/lance-index/src/optimize.rs) | Public pool option and its documented contract |
| [create.rs](../../../rust/lance/src/index/create.rs) | Builder API and unsupported configuration rejection |
| [session.rs](../../../rust/lance/src/session.rs) | Distinguish explicitly configured Session spill storage |
| [vector.rs](../../../rust/lance/src/index/vector.rs) | Route resources and preserve supported default paths |
| [bounded_partition_stream.rs](../../../rust/lance/src/index/vector/bounded_partition_stream.rs) | Reservation ownership, admission, result reconciliation, and cache reclamation |
| [builder.rs](../../../rust/lance/src/index/vector/builder.rs) | Quantizer estimates, partition windows, and split/join materialization |
| [append.rs](../../../rust/lance/src/index/append.rs) | Pool propagation and scan byte targets for wide input |
| [ivf.rs](../../../rust/lance/src/index/vector/ivf.rs) | Resource propagation across IVF entry points |
| [ivf/v2.rs](../../../rust/lance/src/index/vector/ivf/v2.rs) | Dataset resource and compatibility tests |
| [ivf_shuffle_memory.rs](../../../rust/lance-index/examples/ivf_shuffle_memory.rs) | Reproducible resource diagnostic and exact data verification |

The implementation diff contains 15 files, 4,001 inserted lines, and 386 deleted lines, including tests and the diagnostic.
There are no dependency or lockfile changes in those two commits.
There is no separate Phase 1 candidate for this task; this report uses the recorded upstream base instead.

```sh
git diff --stat 08ea2c11674daf4791a00388b0bbe4bd9b339121 09d2c8a0deff51d59b77a83f68d54fed2c277710
git diff 08ea2c11674daf4791a00388b0bbe4bd9b339121 09d2c8a0deff51d59b77a83f68d54fed2c277710 -- rust
```
