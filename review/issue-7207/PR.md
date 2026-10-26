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

- Built-in compaction remap outputs are fresh within the call. The proposed public ownership method requires approval.
- Custom remappers preserve their outputs unless they explicitly guarantee exclusive ownership.
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
- If the private-only alternative is selected, public/distributed compaction remap outputs are also excluded.

This draft must be rewritten around the implemented scope and actual results before an upstream PR is considered.
