# Candidate C-r2 validation artifacts

The applicable finite matrix is complete: 108 runs, 99 validated successes,
2 pool failures, 3 confirmed OOMs and 4 expected cancellations. All 55 formal
runs passed. See [REPORT.md](REPORT.md) for gate decisions and limits and
[RUNBOOK.md](RUNBOOK.md) for reproduction and recovery commands.

Native meets its retention threshold. Forced Late improves the measured sparse
wide workload. Early fails controlled-memory claims on the recorded wide cells.
Automatic Late selection, remote/cold performance and first output-write timing
remain unverified. Failures and the original frozen harness are preserved.

Source is in [C.patch](C.patch) and [C-source.tar.gz](C-source.tar.gz).
[freeze.json](freeze.json) records exact source/binary identities and its original
checkpoint parent. Raw records are under runs/, diagnostics/ and logs/.
The append-only run manifest contains planning, terminal and final audit lines;
count unique run IDs, not JSONL lines. No PR or upstream comment was created.
