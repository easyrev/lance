# Issue 7895 Stage 3 evidence

## Branch roles

| Role | Branch | Head |
|---|---|---|
| Pure PR | `feat/7895-rescannable-sources` | `9767241c21d4124dc2f8d24d642abe93c8ca859c` |
| Review | `review/7895-rescannable-sources` | Updated by the Stage 3 evidence commit |

Upstream baseline: `f9a5c662d79ac312d16d8f636cb1feba4e84aee8`.
The tested implementation commit is `9767241c21d4124dc2f8d24d642abe93c8ca859c`.
The open PR keeps its existing source branch name:
`feat/7895-rescannable-sources`.

The pure branch contains only these four commits after the baseline:

1. `cb85f0c3a` `feat(python): preserve replayable write sources through registered adapters`
2. `15a523ffc` `test(python): avoid commit hooks in source retry tests`
3. `031189d9d` `refactor(python): keep write source registry internal`
4. `9767241c2` `feat(python): scan native Lance datasets as merge sources`

## Stage 3 evidence

Start with
[`stage3-2026-10-31/reports/report.md`](stage3-2026-10-31/reports/report.md).
The follow-up corrections and the native-source scan-default analysis are in:

- [`reports/report-followup.md`](stage3-2026-10-31/reports/report-followup.md)
- [`reports/report-native-source-defaults.md`](stage3-2026-10-31/reports/report-native-source-defaults.md)
- [`reports/report-pre-expansion.md`](stage3-2026-10-31/reports/report-pre-expansion.md)
- [`reports/report-stage3.md`](stage3-2026-10-31/reports/report-stage3.md)

The tree contains the benchmark harness, `analyze_plan` text and JSON outputs,
raw run JSON, logs, summaries, environment records, wheel hashes, and the
verification logs.

Two diagnostic patches are preserved as historical files:

- [`patches/native-source-64mib.patch`](stage3-2026-10-31/patches/native-source-64mib.patch)
- [`patches/parquet-scanner-variants.patch`](stage3-2026-10-31/patches/parquet-scanner-variants.patch)

Neither patch was adopted. No Commit 3 was created. The native-source patch
introduced a new 64 MiB constant instead of matching an existing default. No
Parquet scanner variant met every memory, wall-time, and CPU condition.

Generated datasets, wheels, virtual environments, build caches, and files from
the host environment directory are not included. The unrelated Blob V2 issue
draft is also excluded because it duplicates issue 6372.

## Verification at 9767241

| Check | Result |
|---|---|
| `cargo test -p lance merge_insert` | 434 merge-insert unit tests and 1 integration test passed; 0 failed |
| `cargo test -p lance-datafusion` | 266 unit tests and 3 integration tests passed; 2 ignored; 0 failed |
| `cargo test --no-default-features dataset::replayable::tests --lib` from `python/` | 4 passed; 0 failed |
| `uv run --no-sync --frozen pytest -q python/tests/test_dataset.py` | 424 passed; 5 skipped; 3 warnings |
| `uv run --no-sync --frozen make lint` from `python/` | Ruff format passed for 177 files; Ruff checks passed; Pyright reported 0 errors and 18 warnings; binding formatting and Clippy passed |
| `cargo fmt --all --check` | Passed |
| `cargo clippy --all --tests --benches -- -D warnings` | Passed |

The Clippy build emitted only four informational build-script notices that
FP16 kernels were disabled. The `-D warnings` check did not fail.

Raw logs and timing records are under
[`stage3-2026-10-31/tests/`](stage3-2026-10-31/tests/).

## Packaging checks

The pre-commit credential scan covers every file in this directory. It checks
the active OSS credential and bucket values, common cloud and source-control
token shapes, credential assignments, and session-link patterns. Actual bucket
and endpoint values are replaced with typed placeholders. The required
`/root/.lance-bench/oss.env` path remains literal so the harness contract is
unchanged. The scan result is recorded in
[`CREDENTIAL_SCAN.md`](CREDENTIAL_SCAN.md).

`SHA256SUMS` records every evidence file except itself.
