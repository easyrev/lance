# fix(index): reclaim index directories from lost commits

## Problem

A transaction can write `_indices/{uuid}/` before its commit finishes. If the
commit loses to another writer, no manifest references that UUID, but the
directory remains. Conservative cleanup keeps unreferenced directories for
seven days. A workload that repeatedly loses commit races can therefore grow
the table rapidly, as reported in
[#7207](https://github.com/lance-format/lance/issues/7207).

The prior approach in [#8118](https://github.com/lance-format/lance/pull/8118)
assumed that an `apply_commit` error proved the manifest had not landed. That is
unsafe. A commit handler can land the manifest, then return an error when
`propagate_commit_error_after_success()` is true, which is the trait default.
The [closing review](https://github.com/lance-format/lance/pull/8118#issuecomment-5165503671)
identified `commit_transaction`'s verified-loss arms as the correct boundary.

## Change

The commit call now carries a private cleanup mode. Internal operations whose
index IDs are owned by that call collect candidate UUIDs across the original
transaction and every rebase attempt. A helper runs beside the existing
transaction-file cleanup only after:

- commit-outcome verification returns `Foreign` or `Absent`; or
- retries terminate after a verified loss; or
- a terminal `check_txn` conflict proves that this attempt stopped before any
  transaction-file or manifest write, and the loop reached that point only on
  the first attempt or after a prior verified loss.

The helper reads the latest manifest and its index list at cleanup time. If
either read fails, it logs and skips deletion. It subtracts every UUID in the
latest manifest's index list, then removes the remaining owned
`_indices/{uuid}/` directories. The original commit error is preserved; delete
failures are best effort and are logged separately.

The mode distinguishes three ownership cases. `CallerOwned` disables cleanup.
`TransactionOwned` covers default `compact_files()` with its internally created
remapper. `TransactionExceptRemaps` preserves every
`rewritten_indices[].new_id` returned by a caller-supplied
`IndexRemapperOptions`, while still reclaiming fragment-reuse IDs that the
commit path minted. The public `commit_compaction()` entry uses the conservative
`TransactionExceptRemaps` mode because its remapper trait does not promise that
an output UUID is unique to one invocation.

The collector excludes `new_id == old_id`, which is the `RemapResult::Keep`
case. It accumulates fragment-reuse IDs even after a rebase replaces the UUID in
the transaction, and it includes the tagged assembly returned by
`finish_rewrite`.

## Ownership and replay

| Operation/path | Ownership decision |
| --- | --- |
| Default `compact_files()` Rewrite with the built-in remapper | Transaction-owned; the UUIDs are generated inside this commit call and are not returned in `RewriteResult`. |
| Public `commit_compaction()` or `compact_files()` with a caller-supplied remapper | Remapped-index IDs are caller-owned and preserved; the remapper may return the same `new_id` on a replay. Fragment-reuse IDs minted by the commit path remain transaction-owned. |
| Fragment-reuse UUID created during initial assembly or rebase | Transaction-owned; the value is minted inside the call. |
| Consumed `CreateIndexBuilder::execute` with no caller UUID | Transaction-owned; the builder mints the UUID and returns only after commit. |
| Generic `Dataset::commit` or Python caller transaction | Caller-owned; the same operation and IDs can be submitted again. |
| `execute_uncommitted`, distributed index builds, `commit_existing_index_segments`, and explicit `index_uuid(...)` | Caller-owned; incomplete publication and retries reuse the supplied IDs. |
| Caller-supplied Rewrite through `Dataset::commit` | Caller-owned; the commit layer cannot prove whether the IDs are replay IDs or IDs minted for this call. |

## Tests

| Test | Guard protected |
| --- | --- |
| `test_rewrite_loss_reclaims_remapped_index_directory` | Verified-loss cleanup removes the remapped UUID and keeps a live index directory. |
| `test_rewrite_loss_keeps_custom_remapper_index_for_replay` | A caller-supplied remapper's directory survives verified loss, and the same UUID remains usable on retry. |
| `test_deferred_rewrite_loss_reclaims_spilled_fri_directory` | Deferred fragment-reuse directory cleanup. |
| `test_rebased_fri_loss_reclaims_original_and_replacement_directories` | IDs from earlier and replacement rebase attempts are accumulated and removed. |
| `test_create_index_loss_reclaims_new_index_directory` | A generated internal CreateIndex UUID is removed after verified loss. |
| `test_landed_index_commit_returning_error_keeps_directory` | A landed manifest returning `Err` is never treated as loss or cleaned. |
| `test_rewrite_preempted_by_delete_reclaims_remapped_index_directory` | The reporter's pre-write Delete preemption path cleans terminal owned IDs. |
| `test_collect_transaction_index_ids_skips_keep_remaps` | The collector does not add a kept UUID. |
| `test_lost_index_cleanup_keeps_latest_manifest_index` | Latest-manifest referenced UUIDs are subtracted before deletion. |

All tests compare directory-name sets. The injected error is asserted before
the directory outcome, so an earlier setup failure cannot make a cleanup test
pass vacuously.

## Verification

Tested pure commit: `a108f280a22e1654317f75ce57e18ae8f5cd382e`.

| Check | Result |
| --- | --- |
| Nine targeted tests | Passed |
| `dataset::tests` | 991 passed, 1 ignored |
| `dataset::optimize::tests` | 365 passed |
| `dataset::write::commit::tests` | 18 passed |
| `index::create::tests` | 87 passed |
| `io::commit::tests` | 65 passed |
| `utils::test::tests` | 6 passed |
| `cargo fmt --all --check` | Passed |
| `cargo clippy -p lance --all-targets -- -D warnings` | Passed |
| `RUSTDOCFLAGS='-D warnings' cargo doc -p lance --no-deps` | Passed |

Seven temporary source removals were checked independently. Each was caught by
its named test: UUID collection, rebase accumulation, live-manifest
subtraction, Keep filtering, reporter preemption cleanup, verified-loss cleanup,
and custom-remapper ownership.

## Measurement

End-to-end optimize/delete race measurement is **not measured** for either
`88d8b1cc7` or `a108f280a`. The required unit tests provide the correctness
evidence. The optional script and explicit result table live on the review
branch under `review/issue-7207/bench/` and `review/issue-7207/results/`.

## Out of scope

- Data files. A replayed `RewriteResult` can carry data paths from an earlier
  attempt, so a verified loss of the replay is insufficient proof that those
  paths were never published. See #7722.
- The FTS half-written active-index failure in the rafidowla report. That needs
  separate handling for a directory that becomes selected while incomplete.
- Caller-owned and replayable index operations listed above.
- Remapped-index directories on the public `commit_compaction()` path and on
  custom-remapper `compact_files()` calls. Those IDs are retained because the
  trait does not prove per-call ownership.
- Non-commit rebase-construction failures that have already written an index
  directory. This patch stays at the verified commit-outcome boundary.

## Relationship to #7207

This change follows the ownership proposal in the
[issue comment](https://github.com/lance-format/lance/issues/7207#issuecomment-6408548007)
and is submitted for maintainer review before an upstream PR is opened.
