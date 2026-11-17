# Issue 7207: reclaim index directories of failed commits — review notes

Reproduction, evidence, and prior reports for the fix on
`fix/7207-failed-commit-index-cleanup`. Nothing here is part of the fix branch.

## Branches and commits

| Role | Ref | Commit |
| --- | --- | --- |
| Pure PR | `fix/7207-failed-commit-index-cleanup` | `794031b87` (tip) |
| Review | `review/7207-failed-commit-index-cleanup` | this branch: pure tip plus `review/issue-7207/` commits |
| Upstream baseline of the fix | `upstream/main` | `d8293547c` |
| Upstream baseline of the trial merge | `upstream/main` | `f5dbd55dd` |
| Upstream PR | not opened | — |

Pure branch history, oldest first:

| Commit | Subject |
| --- | --- |
| `ab6f31589` | `fix: reclaim index directories of commits verified as not landed` |
| `9a49c0174` | `fix: keep caller-named index directories on a failed commit` |
| `794031b87` | `chore: tighten comments on failed-commit index cleanup` |

`794031b87` changes comments only; it adds no behavior.

Pre-rewrite revision of this review branch: `7fa7a7002` — the baseline
`d8293547c` plus the harness committed inside
`rust/lance/src/io/commit/repro_7207.rs`. It carried no part of the fix. That
branch tip was replaced, so old SHAs in earlier notes no longer resolve; the
harness and its recorded output survive under `repro/` and `results/`.

Sibling approaches for this issue, each its own branch pair:

| Pair | What it found |
| --- | --- |
| `fix/` + `review/7207-reclaim-lost-commit-indices` | A caller-supplied `IndexRemapper` supplies its own `new_id`s, so a remapper's directories are not the call's to delete; cleanup must be limited to IDs the call mints. |
| `fix/` + `review/7207-reclaim-lost-commit-indices-option-b` | A tagged fragment-reuse rebase mints a fresh UUID and spills `_indices/{uuid}/details.binpb` past the inline limit, and that UUID is not in the transaction's `Operation`, so cleanup has to collect it from the assembly entry or leak it. |

## What to review

That a failed commit removes only index directories the same call minted, and
only once the attempt is proven not to have landed: not on a landed commit, not
between retries, not on an unknown outcome, and never for a directory named by
the caller. The riskiest shapes are a commit that lands but still returns an
error, a rebase that replaces a fragment-reuse UUID, and a caller-owned
transaction that a caller replays.

## Design and scope

Cleanup is opt-in per call site. `commit_transaction` reclaims on a verified
`Foreign`/`Absent` outcome; `commit_rewrites` (compaction) and the single-segment
`CreateIndexBuilder::execute` are the two call sites that opt in. Everything
else keeps the existing behavior, in particular `CommitBuilder::execute`,
because a caller may replay the same segments.

Candidate directories are the IDs the transaction minted, minus the IDs the
latest manifest still references. `CreateIndexBuilder` skips the whole path when
the caller named the directory through `index_uuid`, and compaction skips it when
a remapper cannot promise fresh IDs (`IndexRemapper::creates_fresh_index_ids`).

- In scope: `Operation::CreateIndex` and `Operation::Rewrite` commits issued by
  those two call sites.
- Out of scope: the gaps listed below, FTS half-written directories, and any
  change to public API signatures.
- Earlier reports: `reports/REPORT.md` (first implementation),
  `reports/HANDOFF_SUPPLEMENT.md` (checkpoint that stopped on the remapper
  hole), `reports/SUPPLEMENT_REPORT.md` (ownership guards and full verification),
  `reports/CLOSING.md` (this round: comment cleanup, trial merge, branch rebuild).

## How to reproduce

`repro/repro_7207.rs` is a test harness, not part of any fix. `repro/apply.sh`
installs it into an arbitrary checkout.

```bash
review_root=/path/to/a/checkout/of/this/branch

git worktree add --detach /tmp/7207-check <tested-commit>
(cd /tmp/7207-check && bash "$review_root/review/issue-7207/repro/apply.sh")
(cd /tmp/7207-check && cargo test -p lance --lib repro_7207 -- --nocapture)

git worktree remove --force /tmp/7207-check
```

The harness writes 200 rows in 20 fragments, builds one BTree index, then runs 20
rounds of "plan compaction, inject a DELETE just before the Rewrite conditional
put". It counts `_indices/{uuid}` directories the latest manifest does not
reference, and their bytes.

Environment for every run recorded here: macOS aarch64 (10 cores), rustc 1.98.1
as pinned by `rust-toolchain.toml`, local filesystem storage. The fix branch was
also verified on Linux in an earlier round, per `reports/SUPPLEMENT_REPORT.md`.

## Results by revision

Each row names the commit it tested. Earlier runs do not validate later commits.

| Date | Tested commit | Relation to fix tip `794031b87` | Orphan dirs | Orphan bytes | Raw data |
| --- | --- | --- | --- | --- | --- |
| 2026-11-16 | `d8293547c` | baseline, 3 commits before | 20 | 72,760 | `results/7207-results.md` |
| 2026-11-16 | `ab6f31589` | 2 commits before (the tip then) | 0 | 0 | `results/7207-results.md` |
| 2026-11-17 | `d8293547c` | baseline, 3 commits before | 20 | 72,760 | `results/repro-d8293547c.log` |
| 2026-11-17 | `794031b87` | tip, unchanged commit | 0 | 0 | `results/repro-794031b87.log` |

The 2026-11-16 pair was measured before `9a49c0174` and `794031b87` existed; the
2026-11-17 pair re-measures both ends. `9a49c0174` was not re-measured on its
own: it changes which directories may be reclaimed for caller-named UUIDs, which
the harness does not name.

## Mutation checks

Nine mutations, merged from both reports. Every one was applied to the then-current
code, run, and reverted without committing. Labels name the guard the mutation
removes or inverts, because internal plan numbering is not meaningful outside it.

| # | Guard | Mutation | Test that failed |
| --- | --- | --- | --- |
| 1 | cleanup call on the verified-loss path of `commit_transaction` | delete the call | `test_delete_conflict_reclaims_remapped_index_dir`, `test_rewrite_commit_failure_preserves_or_reclaims_index_dirs::case_1_verified_absent`, `test_create_index_after_concurrent_schema_change` (the preempted drop and cast cases) |
| 2 | `!has_unverified_write` on the reclaim decision | reclaim on any returned error | `test_rewrite_commit_failure_preserves_or_reclaims_index_dirs::case_4_landed_then_index_dropped` and `::case_5_unknown_then_index_dropped`; the earlier landed/unknown cases stayed green because the latest-manifest re-read skipped a directory the manifest still referenced |
| 3 | cleanup after the last retry, not inside the `Foreign \| Absent` branch | move it into that branch | `test_retry_after_concurrent_append_keeps_index_dirs` |
| 4 | `CommitBuilder::execute` passes `ReclaimOnLoss::None` | pass `MintedIndexDirs` | `test_failed_commit_keeps_caller_owned_index_segment` |
| 5 | `new_id != old_id` candidate filter | drop the filter | `test_minted_index_uuids_collects_only_new_ids` |
| 6 | `caller_named_index_dir` branch in `CreateIndexBuilder::execute` | always call `apply_commit_reclaiming_minted_index_dirs` | `test_create_index_after_concurrent_schema_change::case_6_drop_caller_named_uuid` (assertion: `the caller-named index directory must be kept after the preempted CreateIndex`) |
| 7 | the same branch | invert it | `test_create_index_after_concurrent_schema_change::case_6_drop_caller_named_uuid`, `::case_1_drop_indexed`, `::case_3_cast_indexed`, `test_concurrent_create_index_same_name_returns_retryable_conflict` |
| 8 | `IndexRemapper::creates_fresh_index_ids` default of `false` | default to `true` | `test_custom_remapper_index_dir_survives_preemption` (assertion: `a directory behind a caller-supplied remapper's id must survive a failed commit`) |
| 9 | `DatasetIndexRemapper::creates_fresh_index_ids` override | delete the override | `test_delete_conflict_reclaims_remapped_index_dir` (assertion: `the remapped directory of the rejected rewrite must be reclaimed, and the original index directory must survive`), `test_rewrite_commit_failure_preserves_or_reclaims_index_dirs::case_1_verified_absent` (assertion: `a verified-absent commit must reclaim the directory it minted`) |

## Known gaps

Confirmed or suspected leaks left out of the fix. Merged from the known-gaps
section of `reports/REPORT.md`, the tagged fragment-reuse correction and the
old-branch comparison in `reports/SUPPLEMENT_REPORT.md`.

1. Caller-supplied transactions (`CommitBuilder::execute`,
   `commit_existing_index_segments`, `execute_uncommitted`). The caller may
   replay the same segments, so the directories stay. The CreateIndex variant is
   pinned by `test_failed_commit_keeps_caller_owned_index_segment`; the Rewrite
   variant runs through the same default and has no dedicated test.
2. Successful commits that leave fragment-reuse directories behind. When v0
   fragment-reuse details exceed the inline limit, every rebase mints a new UUID
   and writes `details.binpb`; a first attempt that returns `Foreign` followed by
   a successful one leaks the first directory. The success path was left
   untouched.
3. Tagged fragment-reuse rebase directories. A tagged rebase mints a fresh UUID
   and writes `_indices/{uuid}/details.binpb` once the details pass
   `FRAG_REUSE_INLINE_DETAILS_LIMIT` (204,800 bytes). That UUID travels through
   the in-memory rewrite assembly and is absent from the transaction's
   `Operation`, so neither the failure path nor the success path reclaims it.
   (An earlier report recorded this as "no leak"; the correction is in
   `reports/SUPPLEMENT_REPORT.md` section 5.2.)
4. Multi-segment FM-Index builds and `optimize_indices`. Their other
   `apply_commit` calls stay opted out, so a failed commit still leaks the
   directories they wrote.
5. Detached commits and new-dataset commits. They do not reach the opted-in call
   sites.
6. FTS half-written directories, reported in the issue by another user. Not
   handled.
7. A commit that lands after the manifest build drops an index that the remap
   had already written (for example an invalidated overwrite). Only failed paths
   reclaim, so a successful commit can leave an unreferenced remap directory.
   Not measured; recorded as possible.
8. Indices that carry `base_id` are skipped by the candidate filter, so their
   directories are never reclaimed. In practice they are not minted.
9. No end-to-end test that a fragment-reuse directory minted by the call is
   reclaimed after a verified loss. The rewrite cases cover remapped index
   directories only; the kept half of the behavior is pinned at unit level by
   `test_cleanup_keeps_index_dir_referenced_by_latest_manifest`.
10. No test for a rebase followed by a terminal failure, for either the v0 or the
    tagged shape. The tagged variant necessarily fails today, per gap 3.
11. No test that a v0 fragment-reuse directory spilled by
    `build_frag_reuse_index_metadata` is reclaimed when the deferred rewrite is
    verified absent.
12. No test for cleanup's own failure branches: a delete failure and a
    `resolve_latest_location` failure must both keep the original commit error.
    The existing injected-resolve-failure case exercises the commit verification
    instead.
13. No test for `TooMuchWriteContention` (retry timeout) asserting that
    directories are reclaimed, and no end-to-end "index kept across a concurrent
    drop" combination.

## Files

| Path | Purpose |
| --- | --- |
| `README.md` | This entry point. |
| `reports/REPORT.md` | First delivery report: implementation, tests, leak measurement, known gaps. |
| `reports/HANDOFF_SUPPLEMENT.md` | Checkpoint report that stopped on the caller-supplied remapper hole. |
| `reports/SUPPLEMENT_REPORT.md` | Ownership guards, full verification, tagged fragment-reuse correction, old-branch comparison. |
| `reports/HANDOFF_CLOSING.md` | Closing handoff this round executed. |
| `reports/CLOSING.md` | Closing report: comment cleanup, trial merge, branch rebuild. |
| `repro/repro_7207.rs` | Reproduction harness. |
| `repro/apply.sh` | Installs the harness into a checkout. |
| `results/7207-results.md` | 2026-11-16 raw output, labelled with the commits it measured. |
| `results/repro-d8293547c.log` | Baseline run, 2026-11-17. |
| `results/repro-794031b87.log` | Fix-tip run, 2026-11-17. |
