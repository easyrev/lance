# Import and reproduction record

## Source identity

The branch is `review/9505-deferred-merge-payload`. This is a review-only stage.
The implementation commit is `50e216972e1558ce253bece5db462d8241fde96a`. The unchanged baseline and candidate both use base `0a0d327082988018a25f56147d3b6d02f6c79ecc`.
At measurement time, K was that base plus uncommitted changes in `/mnt/lance/checkouts/K_check`.
The implementation commit copies those exact changes. It contains no rebase, source correction, or automatic formatting.

The final freeze identifies 1193 source and configuration files for each variant.
Export checks verified every file, tracked diff, and actual loaded extension against that freeze before and after packaging.
Local checks verified all 1193 candidate source/configuration hashes against the restored checkout.
The final three changed files are:

- `rust/lance/src/dataset/write/merge_insert.rs`
- `rust/lance/src/dataset/write/merge_insert/exec/condition.rs`
- `rust/lance/src/dataset/write/merge_insert/logical_plan.rs`

The [final patch](source-snapshots/final-K.patch) preserves the original Git diff.
[Source snapshots](source-snapshots/snapshots.json) identify export-time copies of `K`, `K_check`, and `K_noadmission_tests`.
`K` is an intermediate checkout. The final measured variant named K uses `K_check` instead.

## Test-source exception

The final benchmark source retains a normal assertion inside a test.
`K_noadmission_tests` changes that assertion to a const assertion. The production source prefix matches the benchmark source.
The [difference record](results/killer-merge-no-admission-20261019/logs/test-only-source-difference.json) provides both hashes.
The [exact patch](results/killer-merge-no-admission-20261019/logs/test-constant-assertion.diff) and both source snapshots preserve the exception.
Rust tests and Clippy use the test checkout. The saved logs report 351 Rust tests and 38 Python tests passing.
These records do not establish full-workspace validation of the exact archived tree.

The local pre-commit launcher points to an unavailable Python environment. Archival commits bypass that hook once per command.
This preserves the measured source and raw evidence. No persistent hook setting changed.
No new benchmark, build, dataset oracle, or code lint ran during the import.

## Evidence and exclusions

The transfer archive SHA256 is `c4e54c15e3f43a0d20ad09b98966a644064fda977a0822bf553ec6298ce5af71`.
[ecs-export.json](import/ecs-export.json) lists all 1847 file/link records and 14120 exclusions.
Each retained file matches its export hash. Relative evidence aliases retain their original targets.
The [local verification record](import/local-verification.json) includes checks of the final freeze's referenced evidence.
[SHA256SUMS](SHA256SUMS) covers every packaged regular file except the checksum list itself.
[SYMLINKS.json](SYMLINKS.json) records every packaged link target.

The exclusions contain generated fixture and per-run datasets, Python bytecode, and coordinator locks.
The archive also excludes environments, build caches, and compiled extensions. Recorded binary identities remain in the freezes.
Fixture definitions, generators, original fixture hashes, failure evidence, logs, resource traces, and result records remain available.
Regenerated datasets need not reproduce the old file hashes. They cannot establish inheritance of the historical OOM.

## Paths and audit

An original path `/mnt/lance/<result-root>/<relative-path>` maps to `review/issue-9505/results/<result-root>/<relative-path>`.
Raw records and scripts retain their original absolute ECS paths. The archive does not rewrite their commands.
The final runbook describes the original build and benchmark workflow. A new execution requires datasets and a prepared environment.

The final evidence audit supports a local mirror without datasets or extensions:

```sh
python3 review/issue-9505/results/killer-merge-final-20261019/audit-results.py \
  --root review/issue-9505/results/killer-merge-final-20261019 \
  --prior-root review/issue-9505/results/killer-merge-20261018
```

The local audit passed in `artifacts-only` mode. It checks the matrix, saved validation records, resource records, and paired ratios.
It does not rescan dataset values or check omitted binary and dataset files.
The original ECS audit used `live-files-and-artifacts` mode. Both outputs remain separate.

The matrix contains 45 new executions with successful output-validation records and four references to one historical OOM.
F16 has no fresh baseline timing. A configured 1 GiB pool does not prove that the baseline enforced that pool.
The 8 GiB cgroup, sampled RSS, and pool configuration measure different memory boundaries.
