# Incomplete PR outline — do not submit

Baseline: `46d7bfdda8ac303d5363c851d6883facb249cb56`.
No implementation or test results exist yet. This outline records the intended scope for review.
No repository PR template was found at `.github/*PULL*` or `.github/*pull*` during this investigation.

Proposed title: `fix(compaction): reclaim owned index directories after verified commit loss`

## Problem

[Issue #7207](https://github.com/lance-format/lance/issues/7207) reports index generations stranded by failed compaction commits.
Conservative cleanup retains those unverified directories for seven days.

[The closing comment on #8118](https://github.com/lance-format/lance/pull/8118#issuecomment-5165503671)
explains why cleanup after an `apply_commit` error is unsafe.
Some handlers propagate an error after the manifest is verified to have landed.

## Proposed behavior

Delete exclusively owned index directories only after the commit layer proves terminal loss.
Keep cleanup beside the verified-loss transaction-file cleanup, never between internal retries.
Also cover the reporter's terminal pre-write conflict using the control-flow proof in DESIGN.md.

Ownership is separate from outcome:

- Built-in compaction remap outputs are owned only when compact_files receives remap_options=None.
- Public/distributed commit_compaction calls and calls with custom remappers preserve their remap outputs.
- Compaction-created FRI entries and every rebase-created FRI entry are tracked across attempts.
- Generic Rewrite and CreateIndex inputs remain caller-owned and replayable. They are not deleted.
- Staged/distributed index builds, existing-segment commits, and optimize-index results retain their supplied directories.

Cleanup loads the latest manifest and its indices inside the helper.
It excludes referenced UUIDs and all Keep IDs. Read failure skips deletion.
Delete failure is logged and never replaces the original commit error.

## Validation to supply after implementation

See DESIGN.md for the test matrix and mutation-to-test mapping.
Required evidence remains outstanding: red regressions, baseline-green safety cases, fixed tests,
changed-module tests, clippy, fmt, rustdoc, and mutation tests.
No benchmark was run. Lost commits, orphan directories, orphan bytes, and wall time are not measured.

## Out of scope

- Data files: [#7722](https://github.com/lance-format/lance/pull/7722) demonstrates that replayed RewriteResult paths can belong to an earlier committed attempt.
- The FTS half-written directory that becomes active. This is a different failure.
- Generic replayable index inputs, partial index builds, clone relocation, and unrelated FRI maintenance.
- Public/distributed compaction remap outputs are excluded by the selected private-only approach.

## Follow-up question for maintainers

The claim comment on #7207 included CreateIndex. This implementation excludes generic CreateIndex inputs because callers can retain and replay their UUIDs.
That includes LanceDataset.commit, distributed index builds, commit_existing_index_segments, and commit_optimize_indices.
A verified loss proves only that the current transaction did not publish. It does not make the caller's staged index directories disposable.

Would maintainers want a separate explicit ownership contract for remapper outputs?
Option A would add a provided IndexRemapper::owns_remapped_indices() method, defaulting to false, with the built-in remapper opting in.
That could extend reclamation to public/distributed commit_compaction without treating arbitrary custom outputs as owned.
The current change uses Option B and leaves the public trait unchanged.
CreateIndex would still need its own explicit ownership boundary rather than blanket cleanup by operation variant.

This draft must be rewritten around the implemented scope and actual results before an upstream PR is considered.
