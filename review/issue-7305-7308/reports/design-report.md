# Design and maintainer evidence

This report summarizes the design research performed during implementation.
Upstream links support the reasoning below. They are not an approval of this candidate by maintainers.

## Workload and upstream signals

| Source | Relevant signal | Implication for this candidate |
| --- | --- | --- |
| [#7305](https://github.com/lance-format/lance/issues/7305) | Memory-pool control for shuffle batches and partition construction | Share caller-owned capacity across those stages. |
| [#7308](https://github.com/lance-format/lance/issues/7308) | Reclaimable shuffle and partition scratch | Use the Session spill abstraction for current scratch files. |
| [#7301](https://github.com/lance-format/lance/issues/7301) | Reactive spilling; HNSW outside the stated direction | Bound supported stages and disclose the excluded graph memory. |
| [#9799](https://github.com/lance-format/lance/issues/9799) | Caller-selected pool capacity and sharing | Accept a pool rather than choosing a process-wide capacity internally. |
| [#7314](https://github.com/lance-format/lance/pull/7314) | Same-author precedent: flush on pressure, then reject a document that cannot fit | Supports a minimum-working-set error as a plausible policy. This unmerged precedent is not acceptance evidence. |
| [#7295 review](https://github.com/lance-format/lance/pull/7295#discussion_r3443347478) | Smaller reads should avoid the original large allocation | Set scan byte targets before decoding instead of slicing a retained large buffer. |
| [#7295 workload](https://github.com/lance-format/lance/pull/7295#issuecomment-4723172945) | Large offline IVF_PQ builds; 2–8 GB batches reduce flush groups; k-means can dominate peaks | Let larger pools increase shuffle targets, while excluding training from the budget claim. |
| [#9434](https://github.com/lance-format/lance/pull/9434) | Offset-table caching affects read efficiency | Keep a bounded, reclaimable cache and a disk fallback. Avoid general speed claims from one replay. |

The historical [#7312 draft](https://github.com/lance-format/lance/pull/7312) was unmerged when inspected during implementation.
Its existence does not establish that the current builder path implements these resource controls.
Issue relationships and cross-references describe project organization; they do not establish completion or ownership.

## Chosen policy

The highest-confidence workload is offline IVF construction and maintenance with caller-selected resource capacity.
The policy first uses available capacity, then flushes or reduces concurrent work, and finally rejects an unsatisfied minimum working set.
This decision follows the available code and author precedent. No direct maintainer confirmation of this specific policy was obtained.

Automatic repartitioning would change clustering and index layout. It would also require additional algorithm and persistence work.
This candidate keeps that behavior outside its contract. The caller can increase capacity or choose a more suitable partitioning configuration.

## Implementation decisions

The shuffler registers spillable reservations. Its finite-pool batch target can grow with the pool rather than retaining the default 128 MiB ceiling.
It reserves for retained input and known sorting/interleaving work, then flushes before polling another batch near the target.
Optional offsets have their own reservations and a disk fallback. Admission pressure can release that cache.

The partition scheduler reserves a working-set estimate before materialization.
Reservations follow running work and held results. Cancellation must not free capacity while non-cancellable CPU work still owns buffers.
Known PQ/RQ conversion and fragment-reuse remapping increase the estimate. Source batches are released after concatenation where possible.

The Session spill store controls all four shuffle scratch files: data, offsets, and the metadata scratch for each writer.
Shared spill ownership covers the writer, published handle, asynchronous shutdown, and outstanding readers.
The IO fix is a separate commit so its lifetime behavior can be reviewed independently.

See [the code map](baseline-comparison.md) and [review history](independent-review-history.md) for the affected boundaries and discovered edge cases.
