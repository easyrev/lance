# Resource diagnostic report

The diagnostic demonstrates shuffle resource behavior and data correctness on a deterministic fixture.
It does not measure end-to-end IVF construction or establish optimized throughput improvements.

## Method

[ivf_shuffle_memory.rs](../../../rust/lance-index/examples/ivf_shuffle_memory.rs) streams 262,144 Float32 vectors with 64 dimensions.
Each input batch contains 4,096 rows. The fixture has 64 partitions.
The uniform distribution spreads rows across partitions. The hotspot distribution assigns half the rows to partition zero.

Each budget/distribution pair ran in a fresh process using a debug build. There is one observation per pair.
Budget zero selects an unbounded tracking pool with the default shuffle target.
It is a control within the candidate implementation, not the upstream base or an API call without a pool.
All modes use the same tracked local spill store.

The write timer includes data generation. The read timer includes exact verification of every row and vector.
The reader directly loads complete partitions; it does not exercise the IVF partition-admission scheduler.
The raw JSON was produced during implementation, before the final commit. It does not contain the source or executable hash.

## Observations

Values below are bytes except for the budget label and flush count.

| Distribution | Pool budget | Flush groups | Peak pool reservation | Peak process RSS | Final reservation / spill bytes / spill files |
| --- | --- | ---: | ---: | ---: | --- |
| Uniform | Unbounded | 2 | 135,719,168 | 106,635,264 | 0 / 0 / 0 |
| Uniform | 8 MiB | 32 | 4,541,824 | 57,688,064 | 0 / 0 / 0 |
| Uniform | 32 MiB | 8 | 18,101,248 | 53,846,016 | 0 / 0 / 0 |
| Hotspot | Unbounded | 2 | 135,719,168 | 140,910,592 | 0 / 0 / 0 |
| Hotspot | 8 MiB | 32 | 4,541,824 | 119,390,208 | 0 / 0 / 0 |
| Hotspot | 32 MiB | 8 | 18,101,248 | 109,580,288 | 0 / 0 / 0 |

Every run created four spill files and verified the complete fixture.
The row-ID checksum is `34359607296`; the vector-bit checksum is `17662399169384832` in every case.
See the unchanged [raw JSON](../evidence/resource-diagnostic.jsonl) for times, retained offsets, and disk counters.

The finite pool reservations remained below their respective capacities.
Increasing the budget from 8 MiB to 32 MiB reduced flush groups from 32 to 8 for both distributions.
All reservations and spill handles were released at completion.
The hotspot RSS exceeds the finite pool capacity because direct read-side verification and other allocations are outside the reservations.
Reservation estimates can also exceed measured resident memory; the two quantities are not equivalent.

## Limits and follow-up measurements

There is no optimized before/after benchmark, repetition distribution, cold-cache control, or production-scale training run in this evidence.
The diagnostic does not prove an RSS bound or that arbitrary oversized partitions can build successfully.
It also does not measure concurrent callers competing for a shared pool.
Before claiming a speedup, compare the base and candidate with identical optimized builds, fixtures, cache conditions, and repeated measurements.

To reproduce the diagnostic mode used for these observations:

```sh
for distribution in uniform hotspot; do
  for budget in 0 8388608 33554432; do
    cargo run --locked -p lance-index --example ivf_shuffle_memory -- "$budget" "$distribution"
  done
done
```

For future performance work, use the repository's `release-with-debug` profile and record source/build hashes.
Do not compare those future timings directly with the debug observations above.
