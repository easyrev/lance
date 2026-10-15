# Proposed PR description

This is a review draft. No PR was submitted for this candidate in this task.

Suggested title: `feat(index): share IVF build memory and spill resources`

IVF builds use separate local scheduling limits and scratch paths. Callers cannot share one memory budget across builds, and Session spill caps exclude shuffle files.

This change adds caller-owned `MemoryPool` options to `CreateIndexBuilder` and `OptimizeOptions`.
The current IVF path shares the pool across shuffle buffers, optional offsets, partition admission, and completed results awaiting writes.
It flushes on pressure, limits concurrent partitions, and releases optional offsets before rejecting a minimum working set that cannot fit.
Unconfigured builds retain the existing scheduling policy.

Shuffle data, offsets, and page metadata use the Session `SpillStore`.
A separate fix retains spill ownership through aborted writes and asynchronous shutdown, releasing disk quota with the storage lifetime.

The scope follows current main, which already writes completed partitions directly to final index files.
This change does not serialize in-progress subindexes or add an all-in-memory shuffle path.
Reservations do not cap process RSS. Training, HNSW graphs, unadmitted upstream input, and file codec transients remain outside the accounting.
Unsupported legacy paths reject explicitly configured resources.

Addresses [#7305](https://github.com/lance-format/lance/issues/7305) and [#7308](https://github.com/lance-format/lance/issues/7308).
The caller-owned API follows the direction in [#9799](https://github.com/lance-format/lance/issues/9799).

Validation includes full workspace Clippy, 56 shuffler tests, 29 builder tests, 19 scheduler tests, and two storage ownership tests.
Dataset tests cover build/optimize, fragment reuse with split/join, failure atomicity, legacy behavior, and wide fixed-vector/multivector input.
Default PQ/SQ/RQ/HNSW, NULL, and empty-partition regressions also passed during implementation.
The task recorded successful formatting, 19 spill tests, and four metadata-spill tests; their raw outputs were not retained.

Six debug diagnostic cases verified all row and vector values for uniform and hotspot inputs.
Increasing the finite budget from 8 MiB to 32 MiB reduced flush groups from 32 to 8.
All runs released reservations and spill handles. These observations establish resource behavior, not optimized throughput improvements.

See the [validation report](validation-report.md) for execution stages and source-provenance limits.
