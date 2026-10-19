## wkalt 2026-10-16T15:08:23Z
https://github.com/lance-format/lance/pull/10077#issuecomment-6218447137

Peak memory of one merge, before and after this change.

Reproducer: a table of 25-row fragments with a key column `key`, a 5 MiB binary cell `a` per row, and an empty binary column `b`. The merge upserts 25 rows by `key` with `when_matched_update_all` / `when_not_matched_do_nothing` from a two-column source. Every measurement is one process doing one merge, debug build, with `MALLOC_MMAP_THRESHOLD_=131072` so that RSS tracks the live heap. The numbers are peak VmRSS growth during the merge, in MiB.

**Plan path** (no index on `key`): source `key` + `b`, 25 rows x 10 MiB, one key per fragment.

| table | `LANCE_MEM_POOL_SIZE` | before | after |
| --- | --- | --- | --- |
| 1 GiB (200 rows) | 1 GiB | 2052 | 994 |
| 1 GiB | 512 MiB | 2052 | 891 |
| 2 GiB (400 rows) | 1 GiB | 4075 | 1066 |
| 2 GiB | 512 MiB | 4056 | 1112 |

**Scalar-index path**: a btree on `key` built after the first fragment, with the rest appended, so the index covers none of the merged rows. The source is `key` + `a` (the wide column), and the 25 keys fall in one fragment.

| table | source rows | pool | before | after |
| --- | --- | --- | --- | --- |
| 1 GiB | 25 x 1 MiB | 1 GiB | 1697 | 725 |
| 1 GiB | 25 x 1 MiB | 512 MiB | 1515 | 735 |
| 1 GiB | 25 x 10 MiB | 512 MiB | 2450 | 1134 |
| 2 GiB | 25 x 1 MiB | 1 GiB | 3701 | 1022 |
| 2 GiB | 25 x 1 MiB | 512 MiB | 3522 | 763 |
| 2 GiB | 25 x 10 MiB | 512 MiB | 4457 | 1396 |

Before, the cost tracked the table (about 2x the decoded table on the plan path) and ignored the pool. After, it tracks the pool and the source. One cost is unchanged and out of scope here: when the keys are spread over every fragment, the column-patch writer still rewrites the touched column of each fragment (about 2.9 GB on both tables at a 512 MiB pool).

The regression test `rust/lance/tests/merge_insert_memory_bound.rs` checks heap growth with a counting allocator under a 48 MiB pool. On the original code the index path grows by 806 MB on its 200 MiB table, against a 128 MiB bound.


## wkalt 2026-10-16T20:36:49Z
https://github.com/lance-format/lance/pull/10077#issuecomment-6224224121

> > the schema byte estimate makes wide rows look small.
> 
> Can you justify this claim? Also, shouldn't we estimate size from the input data not just it's schema for small sources? As in, use `.execute_provider()` and pass in [MemTable](https://docs.rs/datafusion-catalog/54.1.0/datafusion_catalog/memory/struct.MemTable.html) as the provider, which _should_ use exact statistics computed from the underlying record batches.

the source of the misestimation is https://github.com/lance-format/lance/blob/42e593fb4ad0e1ccc22c1fa5e3c30bfe92a5384d/rust/lance-encoding/src/decoder.rs#L1968-L1989 in my case. It has a binary column that is getting estimated on the target side as 64 bytes wide, when in reality it is orders of magnitude larger than that, which is causing the target to get used for the build.

## wjones127 2026-10-16T20:41:46Z
https://github.com/lance-format/lance/pull/10077#issuecomment-6224305236

> in my case. It has a binary column that is getting estimated on the target side as 64 bytes wide, when in reality it is orders of magnitude larger than that, which is causing the target to get used for the build.

Hmm. In an ideal world I think we would fix this by having accurate size statistics. I wonder if in absence of that we should just provide `Precision::Unknown` when there are variable width columns in the projection. What do you think of that? I think if the statistics on either side are unknown, the join order rule will just take the input order. And we can keep the input order as source being collected. That would be acceptable to me.
