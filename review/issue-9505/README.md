# Issue #9505: merge source hypotheses

This review-only branch preserves three hypothesis experiments: compressed-size statistics, batch distribution, and generic Take.
The repository source remains at baseline `0a0d327082988018a25f56147d3b6d02f6c79ecc`. The experimental implementation resides under [study/snapshot/](study/snapshot/).
Source-snapshot commit `0a774f3929de1d7f6a23c971cb28b69f78f59969` preserves the compiled source and reconstruction patches. No pure PR branch exists for this study.

## Read the evidence

- [Original entrypoint](study/README.md): scope, identities, and reading order.
- [Report](study/REPORT.md): findings, contribution recommendations, and unresolved limits.
- [Source findings](study/SOURCE-FINDINGS.md) and [architecture](study/ARCHITECTURE.md): mechanisms and design responsibilities.
- [Raw result summary](study/results.md): all records and three-round comparisons.
- [Validation](study/VALIDATION.md) and [reproduction guide](study/REPRODUCE.md): tests, actual binaries, and execution contracts.
- [Import record](IMPORT.md): publication checks, patch completeness, and paths.

The study contains 53 records: 47 successful executions, four controlled pool errors, and two plan-only records.
The 27 paired executions produced six complete three-round comparisons. Stage probes and full merge executions retain separate timing scopes.
Failures and plan-only records supply no successful timing samples.

The experimental checkout contains a port of #10077 and test-only drivers. It is not a selected production implementation.
The report recommends bounded contributions and collaboration rather than a complete replacement PR or a generic late rule.

All 952 original files match the ECS archive. The original 951-entry checksum list remains unchanged.
Local reconstruction matched 1196 frozen source/configuration files and all seven complete changed-source snapshots.
The report extractor reproduced every original result field except the relocated root path.

Run `python3 review/issue-9505/import/verify-archive.py` to check the outer archive hashes.
Generated datasets, IPC outputs, environments, caches, and compiled binaries remain outside this archive.
Archived instructions and commands describe historical work and supply no new authorization.
The [previous common-base study](https://github.com/easyrev/lance/tree/46684bb29b5aca7d7966549ef90180ebf16e346b/review/issue-9505) remains on its original branch.
