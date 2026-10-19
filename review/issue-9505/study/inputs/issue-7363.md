## Background

Partial-schema (subset-of-columns) upserts now run through the v2 DataFusion plan path (`execute_uncommitted_v2` / `create_plan` in `rust/lance/src/dataset/write/merge_insert.rs`). Since Lance implements updates as delete + append, the plan must read the *missing* (non-source) columns for matched rows in order to rewrite full rows.

Today `create_plan` fills those columns via `with_column(field, col("target.<field>"))` above the join (around `merge_insert.rs:1521`). DataFusion projection pushdown faithfully keeps those referenced columns alive, so the **target scan reads the missing columns for every target row**, then the join discards all but the matched ones. For a selective backfill on a wide table this is the read-amplification problem: a ~1% match still scans 100% of the wide columns.

`explain_plan` test `test_merge_insert_subcols_v2_explain_plan` currently *asserts* this behavior — the target `LanceRead` projects the filled column and carries it through `HashJoinExec`.

This is the read-side half of the "efficient merge_insert" work. The write side still rewrites all columns of matched rows (delete + append); that is **out of scope here** (see #4193 / the column-replacement path).

## Approach: late materialization via a physical optimizer rule

Rather than hand-building a take node in `create_plan`, generalize Lance's existing late-materialization mechanism (today scoped to single-scan filters via `MaterializationStyle`, `scanner.rs:245`) into a plan-level **physical optimizer rule** that defers reads across row-reducing operators.

The rule, run after projection pushdown:

1. Find columns that originate from a `LanceScanExec` (fragment-addressable) and are first *used* above a row-reducing boundary (`HashJoinExec`, `FilterExec`).
2. Narrow the scan's projection to drop those columns, ensure it emits `_rowaddr`, and insert a `TakeExec` just above the boundary to fetch them by `_rowaddr`.
3. `CoalesceTake` (`io/exec/optimizer.rs`) already merges adjacent takes.

Consequence: **`create_plan` can stay naive** — its `col("target.<field>")` fill is exactly a "column read by the scan but only used above the join," so the rule defers it automatically. No merge-insert-specific logical node is needed.

### Scope: merge_insert only, for now

To keep blast radius small, apply the rule **only at the merge_insert call site** (in `create_plan`, after `create_physical_plan`), not in the session's global `PhysicalOptimizer` list. Write the rule generically (match any `LanceScanExec` feeding a row-reducing operator); generalizing later is just moving it into the global optimizer rules. A follow-up can enable it for generic queries once it's benchmarked across workloads.

## Components / implementation order

1. **Null-tolerant `TakeExec`** — prerequisite, independently testable. The merge_insert join is an *outer* join, so insert (source-only) rows have a null `target._rowaddr` and must yield NULL for the deferred columns. `TakeExec::map_batch` currently asserts `row_addrs.null_count() == 0` (`take.rs:222`); replace with real handling: take only non-null addresses, scatter back into full-length arrays with nulls at the insert positions.
2. **Late-materialization physical rule** — written generically, applied only at the merge_insert call site. Guards: only defer `LanceScanExec`-sourced columns (never source/one-shot-stream columns, which have no address); verify `_rowaddr` survives to the take point.
3. **Selectivity gate.** Even scoped to merge_insert, a ~100%-match update would regress (sequential scan → random take of every matched row's wide columns). Gate on column width / storage (reuse `MaterializationStyle::Heuristic`: cloud + wide → late) *and* join selectivity. The join-cardinality estimate from the materialized-input work (#4583) is the signal this gate should read; until that lands, fall back to the conservative width/storage heuristic (covers the inherently-selective backfill case).

## Tests

- Flip `test_merge_insert_subcols_v2_explain_plan`: the target `LanceRead` projection must *exclude* the deferred column, and a `Take` must appear above the join.
- Wide-table selective partial update: assert the wide deferred column is not read for all rows (read-bytes / column-not-loaded).
- Inserts (null `_rowaddr` take path), `UpdateIf` referencing a non-source target column (must stay alive via `__action`, not double-fetched), multi-fragment.

## Out of scope

- Write-side amplification (delete + append rewrites all columns of matched rows). The in-place column-replacement write path belongs to #4193.
- Enabling the rule for generic (non-merge_insert) queries.

Related: #4193 (parent), #4583 (materialized inputs / join cardinality), #3481 (non-indexed merge_insert loads too many columns).

