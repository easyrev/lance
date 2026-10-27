# fix(compaction): reclaim owned indices after verified commit loss

Baseline: 46d7bfdda8ac303d5363c851d6883facb249cb56.
Implementation: d09358d6f21ea9c360b4663cf5b242deb97d9ebd.
Draft only. Do not open an upstream PR before the user's review.

## Problem and behavior

[Issue #7207](https://github.com/lance-format/lance/issues/7207) reports index generations stranded when optimize loses to a concurrent writer.
Conservative cleanup retains these unverified directories for seven days.

This change reclaims index directories that the current compaction call exclusively owns, after the commit layer proves terminal loss.
The ordinary LanceDB table.optimize path uses compact_files with remap_options=None, so it is covered.
Public APIs and persisted formats remain unchanged.

[The closing comment on #8118](https://github.com/lance-format/lance/pull/8118#issuecomment-5165503671)
explains why an apply_commit error is insufficient: a handler can propagate an error after its manifest is verified to have landed.
Cleanup therefore stays inside the commit layer, beside terminal verified-loss transaction-file cleanup.
It never runs after Ours or Unknown, or between internal retries.

The reporter's Rewrite-vs-Delete conflict is an additional terminal path.
check_txn rejects the rewrite before the iteration starts a manifest write.
Success, landed-error, and unknown outcomes return immediately, so every earlier attempt must also be a verified loss.
This control-flow proof permits cleanup of exclusively owned indices before returning that original retryable conflict.

## Ownership and replay

| Input or producer | Rule |
| --- | --- |
| compact_files with remap_options=None | Own the built-in remapper's fresh IDs, excluding Keep results |
| Supplied remapper or public commit_compaction | Preserve remap outputs because the caller can replay them |
| FRI entry built within commit_compaction | Owned by this call |
| Fresh FRI entry built by rebase | Owned by this invocation; retain every UUID across attempts |
| Generic Rewrite or CreateIndex transaction | Preserve caller-owned inputs |
| Distributed builds, existing segments, optimize-index results | Preserve caller-owned inputs |

The inventory includes tagged assembly UUIDs, which are not stored in the returned transaction.
It survives retries and retains UUIDs replaced by later rebases.

Cleanup reads the latest manifest and its complete index list inside the helper.
It excludes referenced UUIDs and Keep IDs.
If the read fails, cleanup skips deletion. If deletion fails, it logs the failure and preserves the original commit error.
Only _indices/UUID prefixes are deleted.

The ownership policy is private and ephemeral. It is not serialized into transactions.
Internal commit futures are boxed to keep the retry inventory from enlarging caller futures beyond the lint threshold.

## Tests and protected behavior

The tests compare directory-name sets and pin failures to the intended injected error or pre-write conflict.

| Coverage | Protects |
| --- | --- |
| Owned Rewrite with verified absent outcome | Terminal index cleanup |
| Another manifest references the output | Fresh latest-manifest exclusion |
| Keep after a concurrent index drop | Keep exclusion independent of latest references |
| External v0 and tagged FRI details | Initial FRI and tagged assembly collection |
| Rebase, then terminal loss | All minted UUIDs retained in the inventory; no cleanup between retries |
| Landed error with default propagation and a stale head response | Verified-own gate independent of the live-index guard |
| Unknown outcome | Retention when publication cannot be verified |
| Rewrite preempted by Delete | Reporter path, with zero Rewrite manifest-handler calls |
| Supplied remapper and public compaction | Caller ownership boundary |
| Generic Rewrite and CreateIndex replay | A second commit can use the same staged directories |
| Read/delete failure | Best-effort behavior and original commit-error preservation |
| Exhaustion and retry timeout | Terminal conflict exits |

Baseline production code plus the initial tests fails six leak assertions and passes ten safety cases.
Additional private-boundary cases cover the new ownership entrypoint.
At d09358d6f21ea9c360b4663cf5b242deb97d9ebd, all 19 new cases pass within 1,660 passing affected-module tests (one existing test is ignored). Clippy with all targets and warnings denied, formatting, and Rustdoc with warnings denied pass.
All 13 individual mutations are rejected by matching test failures. README.md records commands and tested commits; MUTATIONS.md maps each protection to its test and raw evidence.

The optional concurrent IVF_PQ storage-growth measurement was not run. No end-to-end orphan-byte reduction is claimed.

## Follow-up question for maintainers

My claim comment on #7207 listed CreateIndex. This patch excludes CreateIndex because the generic operation accepts caller-owned UUIDs that callers can retain and replay.
That includes LanceDataset.commit, distributed index builds, commit_existing_index_segments, and commit_optimize_indices.
Verified loss proves that the current transaction did not publish; it does not make those staged directories disposable.

Would maintainers want an explicit remapper ownership contract in a follow-up?
Option A would add a provided IndexRemapper::owns_remapped_indices() method, defaulting to false, with the built-in remapper opting in.
It could extend reclamation to public/distributed commit_compaction calls while preserving arbitrary custom outputs.
This patch uses Option B and leaves the public trait unchanged.
CreateIndex would still need an explicit ownership boundary rather than blanket cleanup by operation variant.

## Out of scope

- Data files: [#7722](https://github.com/lance-format/lance/pull/7722) shows that replayed RewriteResult paths may belong to an earlier committed attempt.
- The FTS half-written directory that becomes active. Cleanup does not repair that failure.
- Caller-owned Rewrite/CreateIndex inputs and custom/public remap outputs.
- Partial index builds that fail before returning metadata, clone relocation, and unrelated FRI maintenance.

No repository PR template was found. No upstream PR or comment has been created.
