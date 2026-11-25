# Issue 10526 · wide-value page splitting

[Execution handoff](handoff.md) · [Pre-measurement criteria](local-matrix/acceptance.md) · [Machine, revisions and toolchain](local-matrix/versions.txt)

The pure branch `fix/10526-wide-value-page-split` ends at `fde471a51`. The review branch is `review/10526-wide-value-page-split`. This round used upstream `cb8c25692`, the rebased original fix `1fee2feab`, P1 `19636f49c` and P2 `fde471a51`. No upstream PR was opened.

## Measurements

The [combined medians](local-matrix/combined-summary.md) include file size, page count, largest page, encoding and elapsed time per workload. The predeclared limits were 2% file growth and 10% full-scan time growth against the rebased fix. [Per-cohort counts, minima, medians and maxima](local-matrix/timing-ranges.tsv) correspond to the raw [first](local-matrix/first.tsv), [confirmation](local-matrix/confirmed.tsv) and [focused](local-matrix/focused.tsv) matrices. [Format 2.1 and 2.3 readback](local-matrix/version-smoke.tsv) used one trial per case. The timing matrix used local warm-cache, single-writer format 2.2.

## Execution and deviations

The [first build](local-matrix/build-matrix.sh) tested literal P1 and P2 snapshots. Literal P1 recorded 25 existing small-page test failures ([log](local-matrix/test-p1.log)). The [compatibility build](local-matrix/build-compatible.sh) retained all-wide splitting for wholly distinct samples when the configured page budget is below the dictionary budget. Mixed-width and template measurements were repeated. The mostly-wide read median increased 11.2% in the seven-run cohort and 8.3% in the pooled 22 runs. Mostly-short inputs used 31,000-byte short values.

[Writer harness](local-matrix/writer10526.rs) · [Matrix command loop](local-matrix/run-matrix.sh) · [Format smoke commands](local-matrix/run-version-smoke.sh) · [Scoped test commands](local-matrix/reproduce-final-tests.sh). Build scripts contain checkout-specific paths. P1 recorded 142 successful tests and one ignored; P2 recorded 145 and one ignored ([P1 log](local-matrix/test-p1-compatible.log), [P2 log](local-matrix/test-p2-compatible.log)). The smoke run overlapped compilation. Cold-cache reads, remote storage, multi-writer RSS and production distributions were not measured.
