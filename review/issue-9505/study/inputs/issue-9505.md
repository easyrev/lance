## Summary

For a `merge_insert` that does **not** take the indexed path (no scalar index on the join key, or `use_index=false`), `MergeInsertJob::create_plan` joins **target ⋈ source** with the target as the left input. DataFusion's `HashJoinExec` builds its hash table from the left input, and `JoinSelection` cannot swap the sides because the source's statistics are unknown. The whole target table (all columns the write needs) is therefore collected into memory before a single source row is probed. On an ~80M-row, 44-column table a **100-row** partial-schema merge with `use_index=false` OOM-killed a 110 GiB process in 49 seconds.

Version: lance `13.0.0-beta.7` (`ba4192424e`), DataFusion 54.1.

## Where it happens

`rust/lance/src/dataset/write/merge_insert.rs`, `create_plan`:

```rust
let session_ctx = SessionContext::new();                 // unbounded memory pool, no spilling
let scan = session_ctx.read_table(target_provider)?;     // LanceTableProvider over the dataset
...
let mut df = scan_aliased.join(source_df_aliased, join_type, &on_cols_refs, &on_cols_refs, None)?;
```

- `scan_aliased` (the target) is the **left** input. DataFusion 54.1 `HashJoinExec` documents the left input as the build side (`joins/hash_join/exec.rs`: "HashTable and input data for the left (build side) of a join").
- `JoinSelection::should_swap_join_order` swaps only when both sides report `total_byte_size`, or both report `num_rows`. The target side's `FilteredReadExec::partition_statistics` returns `Precision::Exact(total_rows)` when there is no filter; the source is a `StreamingTable` over a one-shot stream (`execute_reader` → `into_stream` → the "Wrap a one-shot stream in a non-replayable StreamingTable provider" helper), whose exec inherits the default `partition_statistics` = `Statistics::new_unknown`. `(Some(81M), None)` → no swap.
- For `WriteSink::RewriteRows` with a partial-schema source, the plan then adds `with_column(field, col("target.field"))` for every dataset column missing from the source, so the target scan projects **all** columns (44 here), and all of them are materialized in the hash table.
- `create_plan_join_type` returns `Inner` for an update-only merge, so nothing about the join type requires the target to be the build side.

The indexed path (`create_indexed_scan_joined_stream`) is not affected: it probes the index and `take`s only matched rows before its `HashJoin`.

## Reproduction

- Table: ~81.6M rows, 494 fragments, 44 columns, BTree scalar index on the join key.
- Request: `merge_insert(on=key).when_matched_update_all()` with `use_index=false`, source = 100 rows × 3 columns (key + 2 updated columns).
- Result: process RSS climbed to the 110 GiB cgroup limit and was OOM-killed (exit 137) 49 s after the request started. No plan_run line was ever logged (the join never finished building).
- The same table handles the indexed path fine: 23k keys across 30 fragments in 28 s.

## Why this matters

`use_index(false)` is the only way today for an SDK/remote caller to get `RewriteRows` semantics for a partial-schema update (`write_mode` is not exposed there yet), and for a scattered narrow update `RewriteRows` is the cheaper mode by lance's own `write_mode` doc. As it stands that knob is a denial-of-service on any large table, with no warning.

## Proposed fixes (any subset)

1. **Make the source the build side**: join `source ⋈ target` (or force a swap) so the hash table holds the small side; the target then streams through as the probe side. The source stream is already buffered/replayable when `spill_for_retry` is on, so a known `num_rows` could also be attached to its statistics to let `JoinSelection` do the swap on its own.
2. **Late-materialize the non-key target columns**: join on the key with `_rowaddr` only, then `take` the full rows for matched row addresses (the indexed path already does this), instead of projecting all 44 columns through the join.
3. **Run the plan under a bounded pool**: use `lance_datafusion::exec::get_session_context(LanceExecutionOptions { use_spilling: true, mem_pool_size, .. })` instead of `SessionContext::new()`, as `update_fragments` already does, so an oversized build side spills or fails with a memory error instead of killing the process.
4. Until then, document on `use_index()` that the non-indexed path materializes the target table.

