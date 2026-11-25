# #10526 Linux benchmark criteria

Baseline cb8c25692 and final d0020f429, using the release-with-debug profile in separate target directories and Python environments.

- File size can grow by at most 2% per input.
- Peak process RSS can grow by at most 10% for writes, full scans and random takes.
- Write wall time can grow by at most 10% in every measured combination. Report the 8-writer, 8-thread comparison explicitly.
- Report process CPU time (user plus system during the write interval) alongside wall time.
- Use the median of the three measured repetitions separately for each metric, variant and combination. Exclude warmups. Use the single file-stage write measurement for its peak RSS comparison. Compare full-precision values and retain all trials.
- Before continuing a dataset, require an exact round trip for both builds. Require identical file size and page count for wide-low-card, wide-constant and narrow. For wide-unique, operationalize approximately 3× as compression between 2.5× and 3.5× for both files.
- Report every miss as measured.
