# Issue 7207 design and evidence map

Baseline: `upstream/main` at `1afd963c16911f1476ba623d5f8037058ec51c2f`
(`perf(linalg): select u8 l2/dot/cosine kernels once via Dispatch (#10103)`).

The phase-one research started at `88d8b1cc7dadf1e27eba67b853d2113ac2c6c318`;
that revision remains the labelled baseline for `logs/red.log`. A final fetch
moved `upstream/main` to `1afd963c1`. The three intervening commits touch only
linalg dispatch, spill-quota accounting, and Python commit lease-context tests;
none touches this patch's implementation files. The pure branch merged the new
baseline and all final green results are labelled `02d6ed30d`.

## Gate decision

The research gate passes with a reduced scope.

- Current `main` does not reclaim `_indices/{uuid}` directories on a verified
  commit loss. The verified-loss arm only calls
  `cleanup_transaction_file` (`rust/lance/src/io/commit.rs:2085-2094`), and the
  retry-exhaustion exit does the same (`rust/lance/src/io/commit.rs:2105-2115`).
- `verify_commit_outcome` distinguishes `Ours`, `Foreign`, `Absent`, and
  `Unknown` (`rust/lance/src/io/commit.rs:235-255`, `:273-349`). Only `Foreign`
  and `Absent` prove that the failed attempt did not create the manifest.
- The reporter's terminal conflict is detected before this attempt writes a
  manifest. It can be handled safely, but the proof and terminal boundary must
  be explicit; see question 1.
- Only transaction-internal operations are in scope. Caller-supplied
  transactions remain replayable and must not trigger deletion.

The cleanup will run only for operations whose index IDs were minted inside the
call that invokes `commit_transaction`: default `compact_files()` Rewrite
operations using the built-in remapper, fragment-reuse entries created during
rebase, and internal committed `CreateIndexBuilder::execute` calls whose UUID
was not supplied by the caller.

`commit_compaction()` is public and accepts an arbitrary
`IndexRemapperOptions`. Its trait contract does not say that a returned
`new_id` was created by this invocation or cannot be reused by a retry. The
public entry and a `compact_files()` call that supplies a custom remapper
therefore preserve all `rewritten_indices[].new_id` directories. They still
reclaim fragment-reuse directories, whose UUIDs are minted by the commit path.

## 1. Commit outcome paths

`commit_transaction` can terminate with an error in these categories.

| Path | Location | Proven not landed? | Decision |
| --- | --- | --- | --- |
| Initial checkout, index load, or similar setup fails | `rust/lance/src/io/commit.rs:1727-1758` | Yes for this call: no commit attempt has started. | No cleanup in this initial PR; this path does not attempt a commit. |
| Catch-up load, write fencing, transaction rebase construction, missing-version check, or `check_txn` fails | `rust/lance/src/io/commit.rs:1790-1824` | Yes for the current attempt: failure precedes transaction-file and manifest writes. Earlier attempts can only be present after a verified loss. | The reporter's `check_txn` path is included as a terminal pre-write loss. Other early returns remain outside the small cleanup patch. |
| Transaction serialization, transaction-file write, target-version check, manifest preparation, migration, validation, or index migration fails | `rust/lance/src/io/commit.rs:1841-1944` | Yes: the manifest write has not started. | No cleanup in this initial PR. |
| `write_manifest_file` reports `CommitConflict`, readback is `Ours` | `rust/lance/src/io/commit.rs:1977-2008` | No, it landed. | Never delete; return success. |
| `write_manifest_file` reports `CommitConflict`, readback is `Foreign` or `Absent` | `rust/lance/src/io/commit.rs:2009-2013` | Yes. | Delete only when the attempt is terminal. An internal retry keeps the directories because a rebased attempt can still use them. |
| `write_manifest_file` reports `CommitConflict`, readback is `Unknown` | `rust/lance/src/io/commit.rs:2014-2022` | Unknown. | Do not delete. |
| A verified-loss conflict exhausts retries | `rust/lance/src/io/commit.rs:2024-2054`, `:2105-2115` | Yes: every failed attempt was verified lost. | Terminal cleanup and return the existing retry-exhaustion error. |
| A verified-loss conflict hits retry timeout or timeout while backing off | `rust/lance/src/io/commit.rs:2046-2050` | Yes: the current attempt was verified lost. | Terminal cleanup and preserve the timeout error. |
| `write_manifest_file` reports `OtherError`, readback is `Ours`, and the handler propagates post-success errors | `rust/lance/src/io/commit.rs:2056-2083` | No, it landed. | Never delete, even though the caller receives `Err`. |
| `write_manifest_file` reports `OtherError`, readback is `Ours`, and the handler returns success | `rust/lance/src/io/commit.rs:2066-2083` | No, it landed. | Return success; no cleanup. |
| `write_manifest_file` reports `OtherError`, readback is `Foreign` or `Absent` | `rust/lance/src/io/commit.rs:2085-2094` | Yes. | Clean transaction file and owned index directories, log cleanup failures, and return the original error. |
| `write_manifest_file` reports `OtherError`, readback is `Unknown` | `rust/lance/src/io/commit.rs:2096-2101` | Unknown. | Do not delete. |
| A successful manifest write completes | `rust/lance/src/io/commit.rs:1964-1975` | No, it landed. | Return success; no cleanup. |

The built-in handler's default is deliberately conservative:

```rust
fn propagate_commit_error_after_success(&self) -> bool {
    true
}
```

See `rust/lance-table/src/io/commit.rs:896-904`. Therefore a plain
`apply_commit` error is not evidence of loss. The implementation will not use
that error as a cleanup gate.

### Reporter's Rewrite-versus-Delete path

`check_rewrite_txn` returns a retryable conflict when a concurrent Delete or
Update touches a fragment the Rewrite replaced:

```rust
if updated_fragments
    .iter()
    .map(|f| f.id)
    .chain(deleted_fragment_ids.iter().copied())
    .any(|id| self.modified_fragment_ids.contains(&id))
{
    Err(self.retryable_conflict_err(other_transaction, other_version))
```

See `rust/lance/src/io/commit/conflict_resolver.rs:1546-1584`. The diagnostic
"preempted by concurrent transaction" is created at
`rust/lance/src/io/commit/conflict_resolver.rs:467-477`.

`commit_transaction` calls `rebase.check_txn` with `?` at
`rust/lance/src/io/commit.rs:1822-1824`, before `write_transaction_file` at
`:1857-1861` and before `write_manifest_file` at `:1946-1962`. It therefore
does not reach a `CommitOutcome` arm. It is still a terminal, pre-write loss:

1. No manifest write has started for this attempt.
2. The loop reaches this point only on its first attempt or after a prior
   `Foreign`/`Absent` result. No prior attempt is unverified.
3. Returning the conflict ends the call; there is no later internal attempt.

The implementation will recognize the returned `check_txn` error at that exact
call site, run terminal cleanup there for internally owned index IDs, and
return the same error. It will not add cleanup to internal retry boundaries.

## 2. Minted index IDs

### Rewrite remaps

The built-in `DatasetIndexRemapper` calls `remap_index`, which allocates
`Uuid::new_v4()` at `rust/lance/src/index.rs:2085`. `commit_compaction` converts
the remapper's results into
`RewrittenIndex` values at `rust/lance/src/dataset/optimize.rs:3774-3794`:

```rust
.map(|rewritten| RewrittenIndex {
    old_id: rewritten.old_id,
    new_id: rewritten.new_id,
    ...
})
```

The transaction stores each `new_id` in
`rust/lance-table/src/transaction/operation.rs:378-387`. The public
`IndexRemapperOptions` contract at
`rust/lance/src/dataset/optimize/remapping.rs:56-80` permits another
implementation to return any UUID, including one retained for replay. The
collector therefore includes `new_id` only when (a) the caller reached the
default built-in remapper through `compact_files()` and (b) `new_id != old_id`.
The public `commit_compaction()` entry and custom `compact_files()` remappers
skip every rewritten-index ID but retain their internally minted FRI IDs.

### v0 fragment-reuse entries

`build_frag_reuse_index_metadata` allocates the entry UUID at
`rust/lance/src/index/frag_reuse.rs:764-775` and, above the inline limit,
writes `_indices/{uuid}/details.binpb` at `:776-798`. The value is installed as
`Operation::Rewrite.frag_reuse_index` at
`rust/lance/src/dataset/optimize.rs:3911-3920` and defined at
`rust/lance-table/src/transaction/operation.rs:84-116`.

### Tagged fragment-reuse entries

`build_tagged_frag_reuse_entry` allocates a fresh UUID at
`rust/lance/src/index/frag_reuse.rs:1910-1922`; oversized details are spilled
under that UUID at `:1944-1972`. `finish_rewrite` assembles it and returns a
`TaggedRewriteAssembly` at
`rust/lance/src/io/commit/conflict_resolver.rs:3068-3097`. `commit_transaction`
consumes that assembly at `rust/lance/src/io/commit.rs:1891-1898`.

### Fragment-reuse IDs minted during rebase

On a v0 history, `finish_rewrite` calls
`build_frag_reuse_index_metadata` again at
`rust/lance/src/io/commit/conflict_resolver.rs:3172-3180`, then replaces the
transaction's FRI at `:3182-3183`. A tagged rebase similarly builds a fresh
entry at `:3094-3097`. Either operation can replace the UUID from the previous
attempt.

The fix will maintain one `HashSet<Uuid>` across the whole call. It starts
from the original transaction, then after every `finish_with_tagged_rewrite`
adds IDs from both the rebased transaction and the returned tagged assembly.
The old UUID therefore remains in the set after the transaction stops carrying
it.

### CreateIndex

`CreateIndexBuilder::execute_uncommitted_impl` allocates the index UUID at
`rust/lance/src/index/create.rs:398-407`. The committed builder path wraps it in
`Operation::CreateIndex` at `:719-727`; the multi-segment path does the same at
`:951-959`. Segment IDs are materialized into `new_indices`.

An explicitly supplied `.index_uuid(uuid)` is caller-owned
(`rust/lance/src/index/create.rs:135-137`); that builder execution will remain
in replay-safe mode.

## 3. Ownership and replay

| Producer/path | Can the same transaction or ID be committed again? | Decision | Evidence |
| --- | --- | --- | --- |
| Generic `Dataset::commit`, including Python `LanceDataset.commit` with `CreateIndex` | Yes. The caller owns the `Operation` and can submit the same transaction. | Do not delete. | `Dataset::commit` accepts `operation: Operation` at `rust/lance/src/dataset.rs:1690-1709`; Python exposes the operation through `python/python/lance/dataset.py:5023` and the binding at `python/src/dataset.rs:3114`. |
| `CreateIndexBuilder::execute_uncommitted` | Yes. It returns metadata to the caller for later commit. | Do not delete. | `rust/lance/src/index/create.rs:176-179`. |
| `commit_existing_index_segments` and distributed index publication | Yes. Segment IDs and files are supplied by the caller and can be retried. | Do not delete. | Public trait declaration at `rust/lance/src/index/api.rs:403-410`; implementation entry at `rust/lance/src/index.rs:3010`; Python binding at `python/src/dataset.rs:2920-2930`. |
| `commit_optimize_indices` / distributed optimize publication | Yes. Results are assembled and committed by the caller. | Do not delete. | `rust/lance/src/index.rs:3406`. |
| Default `compact_files()` Rewrite with the built-in remapper | No caller-visible index IDs. `RewriteResult` contains fragments, version, and row addresses, but no index UUIDs. A replay creates new remap and FRI IDs. | Safe to delete remapped and FRI IDs when the commit is terminal and verified lost. | `rust/lance/src/dataset/optimize.rs:2533-2553`, `:3932-3951`; built-in allocation at `rust/lance/src/index.rs:2085`. |
| Public `commit_compaction()`, or `compact_files()` with a caller-supplied remapper | The caller supplies the remapper and can invoke it again with the same `RemappedIndex.new_id`. The trait gives no per-call ownership promise. | Do not delete `rewritten_indices[].new_id`; FRI IDs remain transaction-owned. | Public entry at `rust/lance/src/dataset/optimize.rs:3482-3487`; arbitrary output at `rust/lance/src/dataset/optimize/remapping.rs:45-80`; retry protection test in `:14005-14121`. |
| Fragment-reuse IDs minted by `finish_rewrite` | No. They exist only in the commit call. | Safe to delete. | `rust/lance/src/io/commit/conflict_resolver.rs:3068-3097`, `:3172-3183`. |
| Internal `CreateIndexBuilder::execute` with no caller-provided UUID | No. The consumed builder mints the ID and returns only success metadata. | Safe to delete. | `rust/lance/src/index/create.rs:405`, `:697-746`, `:764-972`. |
| `CreateIndexBuilder` with caller-provided `index_uuid` | Yes. The caller chose and can retain the ID. | Do not delete. | `rust/lance/src/index/create.rs:135-137`, `:398-407`. |

The implementation expresses this ownership split with three private commit
cleanup modes:

- `CallerOwned`: do not collect or delete transaction index IDs.
- `TransactionExceptRemaps`: collect transaction-owned FRI IDs, but not
  `rewritten_indices[].new_id` values returned by a caller-supplied remapper.
- `TransactionOwned`: collect all IDs minted by the default built-in path.

Only `compact_files()` with `remap_options = None` selects
`TransactionOwned`. The public `commit_compaction()` entry and calls that supply
an external remapper select `TransactionExceptRemaps`. `CreateIndexBuilder`
continues to select between `TransactionOwned` for its generated UUID and
`CallerOwned` for an explicit caller UUID.

A caller-supplied `Rewrite` through `Dataset::commit` is also excluded even though it carries index IDs in its operation. The commit layer cannot prove whether those IDs were minted for this call or retained for replay.

Data files are deliberately out of scope. `RewriteResult` carries the same data-file paths across calls and may be serialized and replayed. The closing comment on #8118 records why a verified-lost replay can still carry paths from an earlier ambiguous success. Index IDs in these selected paths have different ownership properties.

## 4. Overlap with open and recent work

Checked open PRs and recent `upstream/main` history through the baseline above.
The refresh from `88d8b1cc7` to `1afd963c1` adds #10103 (linalg dispatch),
#10231 (spill quota), and #10293 (Python commit lease contexts); none changes
`commit_transaction`, `conflict_resolver.rs`, or index cleanup.

- #9869 touches `merge_insert.rs` and blob cleanup. It does not overlap the
  selected commit/index cleanup files.
- The local #10096 PR1 branch
  `fix/10096-staged-v0-coverage-rebase-20261026` (`6cf03fbcb`) changes
  `rust/lance/src/index.rs`, `conflict_resolver.rs`, and concurrent-reindex
  tests. It can conflict with UUID collection near tagged/v0 FRI rebase code.
- #10146 is the highest structural risk because it splits
  `conflict_resolver.rs`; a localized edit there may need relocation.
- #10034 and #10159 also change commit/conflict-retry semantics and are likely
  to conflict in the result-validation or retry section of the commit loop.
- #9604, #9821, #8400, #9769, and #9960 change Rewrite/FRI behavior and can
  conflict with rebase mint tracking.
- Additional open PRs with textual overlap in at least one selected file are
  #10341, #10037, #10034, #8400, #9769, #9960, #5899, #10121, #10159, #9898,
  #8916, #9947, #9220, #9654, #9651, #9118, #9178, #8655, #9156, #8774,
  #8801, #8614, #8457, #8246, #10164, #8644, #6806, #9821, #10146, #9746,
  #9155, #9150, #8960, #8958, #8957, #8811, #6018, #8952, #10148, #9961,
  and #9816. The earlier research snapshot also identified #10033 and #9271
  as semantic overlaps without a proposed source-file overlap.
- Recent `main` commits touching these areas include #10206, #9914, #9995,
  #10123, #9731, #9631, and #9611. The patch will stay at the verified-loss
  boundary and avoid broad conflict-resolver restructuring.

## 5. Test hooks

`rust/lance/src/utils/test.rs:817-1012` provides
`AmbiguousCommitHandler`:

- `FailOutright` produces a manifest write error with no landed manifest,
  which verification classifies as `Absent`.
- `LandAndConflict` and `LandAndError` land the manifest and exercise `Ours`.
- `fail_next_rewrite` targets Rewrite attempts without consuming the injection
  on a prior ReserveFragments commit.

The propagate-after-success test needs a configurable
`propagate_commit_error_after_success` value; today the test handler always
returns `false` at `rust/lance/src/utils/test.rs:904-906`. The test utility will
grow a setter while keeping its default behavior unchanged.

The reporter-path test will create a stale Rewrite and commit a conflicting
Delete on the same fragment, then run the Rewrite with low retries. Its error
must be `Error::RetryableCommitConflict` with the preemption message, proving the
failure came from `check_txn` before a manifest write.

The custom-remapper ownership test reuses one `Arc<AnswerRemapperOptions>` whose
answer contains a fixed, externally created UUID. It injects a verified loss,
asserts that UUID's directory still exists, then calls `compact_files()` again
with the same remapper and asserts that the successful manifest references the
retained UUID. This catches both deletion on the first failure and a commit that
would otherwise point at a removed directory.

## Implementation invariant

A private ownership mode distinguishes calls that can replay their IDs, calls
that own all IDs, and hybrid compaction calls that own only FRI IDs. The
collector excludes `rewritten_indices[].new_id` in the hybrid case. The commit
loop accumulates minted IDs across attempts. A cleanup helper is invoked only
on terminal verified loss or the proven pre-write preemption path; it:

1. resolves and reads the latest manifest inside the helper;
2. skips all deletion if either read fails, logging the failure;
3. subtracts every UUID in the latest manifest's index list;
4. skips `new_id == old_id` in the collector;
5. recursively removes only remaining `_indices/{uuid}` directories; and
6. logs deletion failures without replacing the original commit error.

The latest-manifest guard is intentionally repeated even though current live
manifest references are normally disjoint from a verified-lost transaction.
It protects replay/custom-remapper interactions and remains mandatory.

