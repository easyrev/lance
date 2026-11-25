# Issue 10526 · Benchmark and validation evidence

The [Linux 64-vCPU benchmark](linux-64cpu/README.md) compares the fixed upstream and final commits across nine datasets, read tests and the concurrent write matrix. [Summary](linux-64cpu/summary.md) · [Raw records](linux-64cpu/raw/)

## Mac issue-scale validation

Pure branch `fix/10526-wide-value-page-split` at `d0020f429` includes P1, P2 and the follow-up to the empty-value and dictionary-entry checks. Review branch `review/10526-wide-value-page-split` carries this record. Upstream baseline is `cb8c25692`. No PR opened.

[Handoff](handoff.md) · [Execution record, host and reproduction commands](issue-scale/README.md) · [Current PR draft](pr-draft.md)

[Benchmark medians, ranges and raw data](issue-scale/benchmark-results.md) cover one 4.5 GB batch in format 2.2, three measured trials per build, full scan and sorted random take after write. The first shared-target attempt reused a build artifact. The reported trials used separate build directories.

[Verification results and command logs](issue-scale/verification-results.md) include the corrected byte-typed test fixture, the Python installation retry and two upstream-identical Arm64 unreachable expressions reported by strict workspace Clippy. The benchmark used highly compressible distinct values. Cold-cache and multi-writer behavior were not measured in this round.
