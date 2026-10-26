# Issue 7207: design review before implementation

Baseline: `46d7bfdda8ac303d5363c851d6883facb249cb56` (`upstream/main`, fetched for this investigation).

Status: Option B approved by the user. Phase 2 starts with regression tests.
The public IndexRemapper trait must remain unchanged. No test or measurement result is claimed yet.
All source line numbers below refer to this baseline, not the original checkout.

## Decision to review

Commit outcome and artifact ownership are separate facts. The transaction records UUIDs, but does not prove ownership of their directories.
Both `Rewrite` and `CreateIndex` can enter through public APIs with caller-owned, replayable UUIDs.
Therefore, collecting every UUID from either operation and deleting it after verified loss is unsafe.

Selected scope (Option B):

- Clean remapped indices only when compact_files receives remap_options=None and creates the built-in remapper.
- Clean the fragment-reuse entry created inside that `commit_compaction` call.
- Track fresh fragment-reuse entries created by each rebase, including tagged assemblies outside the transaction.
- Preserve caller-supplied `Rewrite` and `CreateIndex` artifacts. Do not infer ownership from an operation variant.
- Preserve data files, caller-owned row maps, and all artifacts after an unknown or landed commit outcome.

### Option A: explicit remapper contract (maintainer follow-up only)

Add this provided method to the public `IndexRemapper` trait in
`rust/lance/src/dataset/optimize/remapping.rs:59`:

```rust
/// Whether this remapper exclusively owns the new index directories it returns.
///
/// Returning true guarantees that every result with different old and new IDs
/// was created by this remap call. Those IDs must not be reused by another call
/// or published independently. Results with equal IDs remain borrowed.
///
/// The commit layer may delete owned directories after a verified terminal loss.
/// The default preserves caller-owned directories for replay.
fn owns_remapped_indices(&self) -> bool {
    false
}
```

Only the built-in `DatasetIndexRemapper` initially overrides this method with `true`.
Existing custom implementations compile unchanged and keep their directories.
The default is important: a live-manifest exclusion does not protect a staged directory that a caller intends to publish later.

`commit_compaction` reads this ownership declaration from the remapper instance.
It passes an internal ownership policy through `Dataset` to `commit_transaction`.
The commit layer collects candidate IDs from the transaction under that policy.
Generic `CommitBuilder` and `apply_commit` callers provide no ownership of incoming IDs.
This policy is ephemeral. It is not added to `Transaction`, protobufs, or the file format.

This is an additive public API change, not an implementation change already made.
Approval is needed before editing the trait.

### Option B: no public API change, narrower coverage (selected)

Use a private compaction implementation with an ownership argument.
`compact_files` knows whether the caller supplied a remapper before it substitutes the default
(`rust/lance/src/dataset/optimize.rs:1214`, `remap_options.unwrap_or(...)`).
Only `remap_options=None` grants ownership of remapped IDs.
The existing public `commit_compaction` wrapper grants no ownership of remapped IDs.
It can still grant ownership of its locally built fragment-reuse entry.

This covers the ordinary built-in optimize path without changing a public API.
It leaves remap directories from public/distributed `commit_compaction` calls for GC,
even when those calls supplied `DatasetIndexRemapperOptions::default()`.
The erased trait object does not identify that default implementation.
Do not use UUID freshness heuristics, transaction properties, or type-name comparisons to bridge this gap.

### LanceDB reporter coverage checked before implementation

The reporter used Python LanceDB 0.30.1. Its tag `python-v0.30.1` resolves to
`f5b21c0aa47238bd20d638bfd30c2784eab80ac5`.
The [Python Rust binding, lines 660-664](https://github.com/lancedb/lancedb/blob/f5b21c0aa47238bd20d638bfd30c2784eab80ac5/python/src/table.rs#L660-L664)
constructs `OptimizeAction::Compact { options: ..., remap_options: None }`.
The [Rust optimize helper, lines 148-155](https://github.com/lancedb/lancedb/blob/f5b21c0aa47238bd20d638bfd30c2784eab80ac5/rust/lancedb/src/table/optimize.rs#L148-L155)
forwards that exact option to `compact_files(&mut dataset, options, remap_options)`.
Thus Option B covers the reporter's ordinary table.optimize compaction entry point.

Current LanceDB main was also checked at `982b2a1229ecbce435ed10a24bd0e54d1228f7ca`.
Its binding sets None at `python/src/table.rs:1593-1596`, and its helper forwards it at
`rust/lancedb/src/table/optimize.rs:197-204`. OptimizeAction::All also passes None at line 224.
Source excerpts and exact refs are in `results/lancedb-optimize-path.md`.

## 1. Commit outcomes and every error exit

`rust/lance/src/io/commit.rs:1714-2115` defines `commit_transaction`.
There is one manifest write per loop iteration, at lines 1947-1962 (`write_manifest_file(...).await`).
The following table covers its explicit error returns and fallible `?` expressions.

| Location | Short code quote | What the error proves |
| --- | --- | --- |
| 1740 | `dataset.checkout_version(read_version).await?` | No manifest write in this invocation. Incoming IDs can still belong to a replay. |
| 1754 | `load_all_indices(&read_version_dataset).await?` | Same. No cleanup proposed for this setup failure. |
| 1792 | `load_and_sort_new_transactions(&dataset).await?` | No write in this iteration. Earlier iterations can exist, but only verified losses reach another iteration. |
| 1794, 1830 | `ensure_can_write_manifest(&dataset.manifest)?` | Pre-write rejection, subject to the same earlier-iteration invariant. |
| 1802 | `TransactionRebase::try_new(...).await?` | Pre-write error. Do not infer ownership of the input transaction. |
| 1803 | `rebase.load_current_lineage(&dataset).await?` | Pre-write read/validation error. |
| 1811-1819 | `if rebase.needs_versions(&missing)` | Pre-write retryable conflict because required history is missing. |
| 1823 | `rebase.check_txn(other_transaction, *other_version)?` | Pre-write conflict. This includes the reporter's path. |
| 1826 | `rebase.finish_with_tagged_rewrite(&dataset).await?` | Pre-write error. A partially failed FRI writer can leave artifacts without returning metadata. Such partial builds remain outside the proposed inventory. |
| 1842-1847 | `canonicalize_non_reusable_field_ids(...)?`, `validate_operation(...)?` | Pre-write validation error. |
| 1851 | `pb::Transaction::try_from(...)?` | Pre-write serialization error. |
| 1858 | `write_transaction_file(...).await?` | A transaction file may exist, but the manifest write has not started. |
| 1865-1868 | `if is_detached_version(target_version)` | Explicit pre-write version-range error. |
| 1874 | `build_config_for_attempt(...).await?` | Pre-write configuration/index preparation error. |
| 1879-1888 | `Transaction::restore_old_manifest(...).await?` | Pre-write restore preparation error. |
| 1897-1898 | `prepare_attempt(...).await?` | Pre-write index preparation error. It may create an FRI entry for maintenance, which is not an incoming owned compaction artifact. |
| 1899-1905 | `build_manifest_prepared(...)?` | Pre-write manifest construction error. |
| 1906-1911 | `apply_seed_feature_flags(...).await?` | Pre-write validation/read error. |
| 1925 | `migrate_manifest(...).await?` | Pre-write migration error. |
| 1927 | `fix_schema(&mut manifest)?` | Pre-write schema error. |
| 1928-1932 | `validate_non_reusable_field_id_transition(...)?` | Pre-write field-ID validation error. |
| 1934-1935 | `check_manifest_storage_version_for_commit(...) ?`, `check_fragment_ids(...) ?` | Pre-write compatibility/fragment validation error. |
| 1939 | `migrate_indices(...).await?` | Pre-write index migration error. |
| 1940-1944 | `withdraw_coverage_invalidated_after_build(...)?` | Pre-write coverage validation error. |
| 2014-2021 | `CommitOutcome::Unknown` | The manifest write may have landed. Never delete. |
| 2046-2050 | `timeout_error(...)`, `maybe_timeout(...).await?` | Terminal timeout after a verified foreign/absent attempt. Safe only for owned artifacts. |
| 2080-2081 | `propagate_commit_error_after_success()` / `return Err(err)` | The commit **landed**. Never delete, despite the error return. |
| 2085-2094 | `CommitOutcome::Foreign \| CommitOutcome::Absent` / `return Err(err)` | Terminal verified loss. Existing code deletes only the transaction file. |
| 2096-2100 | `CommitOutcome::Unknown` | Unverified outcome. Never delete. |
| 2107-2115 | `Failed to commit the transaction after ... retries.` | Terminal conflict exhaustion after a verified foreign/absent attempt. Existing code deletes only the transaction file. |

An `Ok` result and `CommitOutcome::Ours` return immediately. Neither can reach another iteration.
The only `continue` is line 2051, after `Foreign | Absent` at line 2013.
There is no cleanup of index directories on these paths in the baseline.

Verification compares the persisted transaction against the attempted protobuf transaction
(`io/commit.rs:297-310`, `committed_transaction == transaction_pb`).
Absence is definitive only when the handler says so (`314-315`, `is_version_not_found_definitive()`).
Read failures and nondefinitive absence can become `Unknown`.
The handler default returns true for error propagation after success
(`rust/lance-table/src/io/commit.rs:902-904`). Do not change this behavior.

### Reporter path: safe alternative to read-back verification

`rust/lance/src/io/commit/conflict_resolver.rs:1567-1583` compares deleted/updated fragment IDs
against the rewrite's modified IDs. An overlap returns `self.retryable_conflict_err(...)`.
The error text is at lines 467-475: `This {} transaction was preempted by concurrent transaction {} ...`.
`commit_transaction` propagates it at line 1823, before writing the attempt's transaction file or manifest.
It does **not** reach a `Foreign | Absent` arm and does **not** consume internal retries.
Setting a low retry count does not change this rejection into a manifest CAS conflict.

Safe cleanup requires both of these facts:

1. The current iteration has not invoked the manifest writer.
2. Every earlier iteration ended in verified loss. Success, landed-error, and unknown outcomes returned immediately.

This proves nonpublication by this invocation. It does not prove ownership of replayable input IDs.
With explicit exclusive ownership, the commit layer can clean up before returning this terminal `check_txn` error.
Keep the original error variant and message. Do not retry it or change handler behavior.
Other pre-write failures are not needed to reproduce the reporter's path and can remain outside the first fix.

## 2. UUID creation and transaction inventory

| Producer | Creation and record | Ownership decision |
| --- | --- | --- |
| Built-in eager compaction remap | `rust/lance/src/index.rs:2085`: `let new_id = Uuid::new_v4()`. `dataset/optimize.rs:3784-3793` copies remapper results to `RewrittenIndex { old_id, new_id, ... }`. Lines 3941-3945 put them in `Operation::Rewrite`. | Fresh for the built-in remapper. A custom remapper needs an explicit contract. |
| Keep result | `index.rs:2076`: `RemapResult::Keep(*index_id)`. `dataset/index.rs:119` handles Keep. | Borrowed. Always exclude equal old/new IDs, including IDs absent from the latest manifest. |
| Compaction v0 fragment reuse | `index/frag_reuse.rs:774`: `let index_id = uuid::Uuid::new_v4()`. Lines 776-785 write `details.binpb` only above the inline threshold. `dataset/optimize.rs:3914-3920` calls the builder and 3944 records `frag_reuse_index`. | Owned by this compaction call. The serialized `RewriteResult` does not carry this newly built entry. |
| v0 FRI rebase | `io/commit/conflict_resolver.rs:3174-3182`: build metadata, then `*new_fri = new_frag_reuse_index_meta`. | Owned by this invocation. Save the previous UUID before replacement and union every newly returned UUID into a persistent inventory. |
| Tagged rewrite intent | `index/frag_reuse.rs:1303-1314`: `uuid: Uuid::new_v4()`. `dataset/optimize.rs:3906` constructs the intent from the read snapshot. | The initial intent is inline. Do not assume every minted UUID has a directory. |
| Tagged rebase assembly | `conflict_resolver.rs:3094-3097`: `build_frag_reuse_rewrite_entry(...)`, then `TaggedRewriteAssembly::new(...)`. `index/frag_reuse.rs:1915-1925` mints and potentially spills a fresh entry. | Owned by this commit invocation. Its UUID is in `assembly.entry`, **not** the returned transaction. Collect it before `tagged_rewrite.take()` in `io/commit.rs:1891`. |
| Ordinary and staged index builds | `index/create.rs:405`: `self.index_uuid.unwrap_or_else(Uuid::new_v4)`. Line 669 puts the output UUID in metadata. Lines 719-724 put metadata in `CreateIndex.new_indices`. Empty/model paths also mint at lines 833 and 903 and record at 876 and 953. | Not uniformly owned: public `execute_uncommitted` returns metadata, and supported builds accept caller-supplied UUIDs. Exclude generic CreateIndex. |
| Distributed vector model/optimization | `index/optimize.rs:731` creates a model UUID. Public `commit_optimize_indices` accepts `Vec<IndexSegmentResult>` at 1161-1164 and records results at 1258-1263. | Caller can retain/replay results. Exclude generic CreateIndex. |
| Existing index segments / merged segments | `index.rs:3010-3025` accepts and converts caller segments. Lines 3254-3264 commit their IDs without minting replacements. | Caller-owned. Never delete supplied IDs. |
| FRI maintenance | `dataset/index/frag_reuse.rs` uses CreateIndex at 185, 314, 461 and 515. Tagged trimming uses `build_tagged_frag_reuse_entry` at 886. | Excluded from the first fix. Do not classify all FRI-looking metadata as owned compaction output. |
| Clone relocation | `index/frag_reuse.rs:2286-2296` mints and spills a relocated entry in the target. | Separate clone path. Excluded from commit_transaction compaction cleanup. |

The inventory must live outside the retry loop. The final transaction alone loses earlier v0 UUIDs
and never contains the tagged assembly UUID. Never delete between retries.
Keep the original borrowed/Keep IDs excluded across all iterations.
Failures inside a builder before it returns metadata require a separate writer inventory and remain out of scope.

## 3. Replay and ownership evidence

`rust/lance-table/src/transaction/builder.rs:11-23` calls Transaction
`A change to a dataset that can be retried` and derives `Clone`.
Its `operation` is public. `rust/lance/src/dataset/write/commit.rs:310` accepts a Transaction in public `CommitBuilder::execute`.
Lines 487-498 pass it to the same `commit_transaction` used by compaction.

Python also exposes both operations. `python/python/lance/dataset.py:6729-6731`
contains `rewritten_indices` and `frag_reuse_index`. Lines 6744-6745 contain CreateIndex metadata lists.
Lines 4944-4950 explicitly require callers to retain merged scalar index output and later publish it with `LanceDataset.commit`.
`index.rs:964-993` even constructs a CreateIndex transaction for staged replay validation.

| Entry path | Decision |
| --- | --- |
| Generic Rust/Python Rewrite transaction | Caller can replay. Do not delete incoming remap or FRI IDs. |
| Built-in compaction remap in a single call | Owned by the call, provided the implementation identity/contract is known. Safe after verified terminal loss. |
| Custom IndexRemapper | Current trait provides no ownership promise. Preserve outputs by default. A latest-manifest check alone is insufficient. |
| FRI built inside commit_compaction | Owned by the call. A new commit_compaction call rebuilds it. Safe after verified terminal loss. |
| FRI newly built inside rebase | Owned by this commit invocation. Record every successful build, including tagged assemblies. Safe after verified terminal loss. |
| Generic CreateIndex, distributed builds, commit_existing_index_segments, commit_optimize_indices | Caller can replay. Exclude incoming IDs from cleanup. |
| Ordinary CreateIndexBuilder with generated UUID | Potentially supportable through a separate private ownership path. Excluded to keep the first change focused and avoid treating all CreateIndex paths alike. |

This is a reduced scope, not a finding that no operation is safe.
Do not delete data files: a replayed `RewriteResult` carries paths an earlier ambiguous success may have committed.
See [the closing comment on #8118](https://github.com/lance-format/lance/pull/8118#issuecomment-5165503671)
and [#7722](https://github.com/lance-format/lance/pull/7722).

## 4. Cleanup algorithm

Proposed private helper precondition:

> This invocation has verified that none of its manifest attempts landed. Each candidate is exclusively owned by this invocation.
> Borrowed transaction inputs and Keep IDs are never candidates. Cleanup is best-effort and must preserve the original commit error.

1. Gather eligible IDs from the owned transaction at entry.
2. Gather newly built FRI IDs after every successful rebase, before replacing or consuming metadata.
3. On terminal verified loss, load the latest dataset manifest inside cleanup.
4. Read its full index metadata, including system indices, inside cleanup. Skip all deletion if either read fails and log the failure.
5. Subtract every referenced UUID. Never use the original handle's stale index list as the live guard.
6. Delete only candidate `_indices/{uuid}/` prefixes. Missing prefixes are expected for inline FRI entries.
7. Log other delete failures and return the original commit error.

Call the helper beside transaction-file cleanup on terminal `Foreign | Absent` outcomes,
on conflict exhaustion, and on timeout after verified loss. Do not call it at the intermediate retry cleanup.
Handle the reporter's terminal pre-write conflict separately with the proof above.
No cleanup follows `Ours`, `Unknown`, cancellation, or a plain `apply_commit` error.
Do not change the commit-handler contract, retry policy, public transaction structure, or persisted format.

## 5. Overlap review

Read [issue #7207](https://github.com/lance-format/lance/issues/7207),
[the claim](https://github.com/lance-format/lance/issues/7207#issuecomment-6408548007),
the maintainer reply, the description of #8118, and both discussion comments.
The issue remains open. The maintainer invited a PR.
The search for PRs referencing 7207 returned only closed #8118.
The broader open-PR search did not reveal an active implementation of this exact cleanup.
These are observations from this investigation, not a guarantee about future submissions.

`results/overlap.json` records the file lists checked for related open PRs.
Possible conflicts for the proposed implementation are:

| Work | Possible conflict |
| --- | --- |
| #9869, analyze-plan cleanup | No shared proposed source file. It cleans data/blob artifacts without committing. Related ownership principle, different implementation. |
| #10096 PR1 branch, `f217e5afa6c06640374b67c59cc536c01e0f974a` | `conflict_resolver.rs` import and CreateIndex-vs-DataReplacement check. Also index.rs and concurrent_reindex tests. No direct hunk overlap with finish_rewrite, but a shared file and replay semantics need review. |
| #10096 PR2, `fix/10096-packed-parent-index-conflict`, `86b4d717d20fbae583456523ee1dd4a8c3b6ac9a` | Rechecked all origin heads. Resolver import and CreateIndex-vs-DataReplacement check, plus concurrent_reindex tests. Shared file but no direct hunk overlap with the proposed rebase inventory. The branch is unchanged. |
| #10146 | Splits conflict_resolver into check/init/finish/test modules. Direct move/edit conflicts for any resolver change or colocated test. |
| #9821 | optimize.rs, remapping.rs, conflict_resolver.rs, FRI maintenance and validation. Shared compaction and conflict-check code. |
| #10148 | dataset/index.rs, optimize.rs, remapping.rs. Direct risk around remapper creation and the proposed ownership method. |
| #9961 | optimize.rs. Shared remap call and compaction setup. |
| #10037 | io/commit.rs. Shared manifest preparation/commit code. |
| #10034 | dataset.rs, optimize.rs, write/commit.rs, io/commit.rs, conflict_resolver.rs. Idempotency and transaction identity need semantic review as well as merge resolution. |
| #9654 | dataset.rs and io/commit.rs. Shared supplied-manifest refresh and commit paths. |
| #9769, #9960 | dataset.rs, optimize.rs, index/frag_reuse.rs, io/commit.rs, conflict_resolver.rs. Direct FRI/compaction ownership and assembly overlap. |
| #9947 | dataset.rs, io/commit.rs, utils/test.rs. Shared coverage preparation and test hooks. |
| #9816 | utils/test.rs. Shared test handler changes. |
| #6806 | conflict_resolver.rs. Staged transaction replay semantics. |
| #10033 | No proposed source-file overlap in its current file list. Commit publication behavior is related and needs semantic review. |
| #9271 | No proposed source-file overlap in its current file list. Index coverage remains related. |

The #10096 identifier is an issue/work identifier, not a pull request returned by `/pulls/10096` (404).
The exact origin branch refs were checked with `git ls-remote` and are saved in `results/10096-remote-refs.txt`.
No matching upstream PR was found by head branch or author/issue search.
No existing local branch or origin branch was changed. The initial query missed PR2 because it did not exist in that snapshot.
The resumed check enumerated every origin head and found the PR2 refs above, plus review PR2 at
`123f6b81b8973975c709c3b9c55b6bd9d7a887a0` (`review/10096-packed-parent-index-conflict`).

Recent main changes include `c64641607` (#10206, read-version state), `ce0f70218` (#9914, manifest encoding),
`4a519a29c` (#10123, overlay rebase), `59d4d98eb` (#10102, seed flags), and `468e56106` (#9808, deferred rewrite exemption).
Their current behavior must remain intact. Full hashes are in `results/recent-commits.txt`.
Refresh this overlap check before implementation publication because open PRs can change.

## 6. Test hooks and planned evidence

Use `AmbiguousCommitHandler` in `rust/lance/src/utils/test.rs:842`.
`fail_next_rewrite` at 877 avoids consuming the injection during fragment-ID reservation.
`FailOutright` returns `simulated outright commit failure` without publishing (977-979).
`LandAndError` publishes then returns `simulated ambiguous commit failure` (961-975).
`LandAndConflict` publishes then reports conflict (947-959).
`fail_resolve` can make outcome verification unavailable (848).

The existing handler overrides `propagate_commit_error_after_success` to false (904-905).
The landed-but-error regression therefore needs a test wrapper that delegates commit and resolution,
but retains the trait default true. Using the existing handler unchanged would test the wrong behavior.
A test-local handler can commit a concurrent operation before returning a conflict to force rebase and terminal loss.
For the reporter path, commit Delete between planning/remapping and check_txn, then assert that the Rewrite handler was never called.
That test should assert the actual retryable conflict text, not an injected manifest-write error that cannot occur on this path.

| Test | Expected baseline behavior | Fix part or mutation protected |
| --- | --- | --- |
| Owned Rewrite, verified loss, live-ID exclusion | Red: newly minted remap directory survives | Cleanup call and fresh latest-manifest guard |
| Keep (`old_id == new_id`) | Green: baseline already retains it | Remove Keep filter in the fixed version to make it fail |
| Deferred rewrite, external FRI details | Red: own FRI directory survives | Initial FRI collection |
| Rebase creates FRI then terminal loss | Red: earlier and later directories survive | Persistent inventory, including assembly UUIDs |
| Generic CreateIndex replay | Green: baseline preserves the caller's artifacts | Reject accidental blanket CreateIndex cleanup; positive deletion test excluded |
| Landed commit with propagated error | Green: baseline preserves referenced directories | Verified-loss gate |
| Rewrite preempted by Delete | Red for owned directory deletion assertion | Terminal pre-write rejection cleanup |
| Unknown outcome, live-list read error, delete failure, custom remapper replay | Safety cases, baseline retention is expected | Conservative skip and original-error preservation |

Compare directory names as sets. Assert the error variant and message, and verify the injection or concurrent operation actually ran.
Use tiny multi-fragment datasets and external FRI content just above the inline threshold.
The Keep and landed-error tests cannot honestly be reported as failing on unmodified main:
main already has their required safety behavior. Record baseline-green protection tests separately from red regression tests.
This is an evidence constraint, not a reason to weaken either assertion.

No tests, lint, docs build, mutation tests, or end-to-end race were run at this design gate.
No red.log was created because there is no measured red result.
The optional IVF_PQ race remains not measured.

## Gate answers

- Already fixed / duplicate PR: not found in the inspected baseline and GitHub searches.
- Reporter path: no read-back verification arm, but the pre-write control-flow proof exists. Ownership is still required.
- No safe operations: false. Built-in compaction outputs and internal rebase-created FRI entries can be owned safely.
- The user selected Option B. No public trait change is authorized or needed for the selected scope.
- If the rebase FRI inventory requires a large diff, report its size before continuing with implementation.
- FTS half-written active indices, data files, generic replayable input IDs, partial builds, and clone cleanup remain out of scope.

Branch separation: the pure branch remains at the baseline with no review paths.
The review branch contains only `review/issue-7207/` additions and has the pure branch as an ancestor.
See `logs/separation.log` for the check.
