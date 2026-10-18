# Issue #9505: merge-insert investigation

This is a review-only branch. It preserves the measured candidate and its evidence for further analysis. No pure PR branch exists for this candidate. The older `fix/9505-small-stream-statistics` branch represents baseline B.

## Start here

- [Final C-r2 report](results/20261018T103247Z-C-r2/REPORT.md): findings, gate decisions, failures, and limits.
- [Reproduction runbook](results/20261018T103247Z-C-r2/RUNBOOK.md): environment, commands, and recovery.
- [Design](inputs/lance-9505-unified-design.md) and [validation brief](inputs/codex-ecs-validation.md): the original research contract.
- [Import record](IMPORT.md): source identity, archive integrity, and path mapping.

## Code and measurements

The implementation commit is `f68d9e88d5ba4d45aa1317fba9b3eb973479826c`.
The base commit is `dc53d5d174af62c49ddd98d1024a64488c1e4404`.
The tested source was that base plus the frozen C-r2 patch, before a Git commit existed. The implementation commit restores those exact source bytes. It contains no rebase or additional code edits.

C-r2 records 108 runs, including 55 validated formal runs. Native reduced F16 merge time by 68.2% against Cbudget. Forced Late reduced Wn merge time by 72.6%. Three Early OOMs remain failures. These results cover the recorded local hot-cache workloads, not general production performance.

[C-r1](results/20261018T092212Z-C-r1/) is a rejected earlier implementation. Keep its failures separate from C-r2. The [earlier statistics investigation](https://github.com/easyrev/lance/tree/3fd5356239b91c0d38e818b0c7237e9545d1db11/review/issue-9505) belongs to a different implementation and measurement method.

Original reports, logs, traces, and manifests retain their contents. This archive excludes generated datasets, Python bytecode, environments, build caches, and compiled binaries. Fixture metadata and generation scripts remain available. Archived task instructions describe the historical run. They do not authorize new actions.
