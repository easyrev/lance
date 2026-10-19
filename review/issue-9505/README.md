# Issue #9505: common-base merge evaluation

This review-only branch preserves a comparison of U, B, P, D, CTX, DB, and DP. It selects no default implementation.
The repository source remains at baseline `0a0d327082988018a25f56147d3b6d02f6c79ecc`. The six candidate implementations reside under [study/ports/](study/ports/).
The source-snapshot commit is `a79a94496f2aeec978438a92c6f8fa5f9adb1736`. No pure PR branch exists for this study.

## Read the study

- [Original research entrypoint](study/README.md): scope, candidate identities, and reading order.
- [Technical report](study/REPORT.md): results, failure boundaries, mechanism choices, and recommended contribution path.
- [Paired results](study/paired-report.md): raw values, ratios, and resource costs.
- [Validation and limits](study/VALIDATION.md): actual builds, tests, and coverage boundaries.
- [Reproduction guide](study/REPRODUCE.md): original commands and contracts.
- [Import record](IMPORT.md): publication identity, local checks, and relocated paths.

The study records 161 executions: 153 successes, seven pool resource failures, and one cgroup OOM.
It also records 23 auxiliary diagnostics. The 87 formal paired executions passed their saved output-validation checks.
Failures and diagnostics retain their original classifications. Neither group supplies successful timing samples.

The research recommends DB as a basis for further work, with regressions and unresolved limits.
It recommends collaboration with #10077 before a complete replacement PR. This archive preserves that recommendation without selecting a candidate for upstream.

## Check the archive

Run `python3 review/issue-9505/import/verify-archive.py` to check all packaged file hashes.
The original 3149-entry study checksum list remains unchanged. All 3150 original files, including that list, match the ECS copy.
All six patches reconstruct the frozen sources on the common baseline. See [patch verification](import/patch-verification.json).
The [local record audit](import/local-artifact-audit.json) passed without workloads, builds, or dataset scans.

The [previous D investigation](https://github.com/easyrev/lance/tree/445001ab15381c5dd6aab8311bce7b0a7245fb72/review/issue-9505) remains on its own branch.
Original evidence and reports retain their bytes. Generated datasets, environments, caches, and compiled binaries remain outside this archive.
Archived agent instructions and commands describe historical work. They supply no new authorization.
