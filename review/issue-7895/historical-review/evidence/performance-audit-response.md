# Performance script review response

The independent review identified random retry backoff as a confounder before final measurements.

`retry.rs:81–90` sets the slot duration from the first failed attempt. `SlotBackoff::next_backoff` selects one of four initial slots.

The evidence scripts now record these additional measures:

- Every commit hook records entry and release times relative to the merge timer.
- `first_commit_elapsed_s` ends before the concurrent update and retry wait.
- `first_commit_cpu_s` records process user and system time before the first hook.
- `cpu_s` records process user and system time across the entire merge, including the concurrent update.
- `concurrent_update_elapsed_s` records the injected update interval.

Conflict trials require commit versions `[2, 3]`. Clean trials require `[2]`. Successful merges must report exactly one update, zero deletions, and the expected inserts.

The summary repeats these checks. The report retains every wall-time sample and adds first-hook and CPU comparisons.

The report states that paired trials do not share random slots. Hook timestamps do not isolate the exact retry wait, so the scripts subtract no estimate.

The review also noted probe logging overhead. The README and report now state that tiny elapsed-time differences can include observation overhead.

Python syntax checks passed after these edits. The independent reviewer completed static review and two diagnostic smoke checks with the development binary.

The clean and conflict checks used eight rows and a 256-byte source. Independent assertions confirmed hook order, CPU fields, versions, and merge statistics.

Raw files are `independent-backoff-smoke-{clean,conflict}.json` and their `.stderr` files. Their diagnostic labels exclude them from the final matrix summary.

These changes affect external evidence scripts only. Final timing remains blocked until both matched snapshots are ready and compilation stops.
