# Delivery report

Candidate: `09d2c8a0deff51d59b77a83f68d54fed2c277710`.
The branch addresses caller-controlled IVF build memory and Session-owned spill storage.

## Resulting behavior

Callers can supply a DataFusion `MemoryPool` through `CreateIndexBuilder::with_memory_pool` and `OptimizeOptions::with_memory_pool`.
The current IVF path shares that pool across shuffle buffers, optional offset caches, partition admission, and completed results awaiting writes.
Callers can share one pool across operations.

Under pressure, the shuffler flushes buffered data. The partition scheduler limits concurrent work and can release optional offsets.
If the minimum admitted working set still cannot fit, the operation returns an error.
Input scans use a finite pool's byte target before materialization, including wide vectors and multivectors.
Append and partition split/join paths also propagate the resource options.

The Session `SpillStore` owns shuffle data, offsets, and their page-metadata scratch files.
Spill ownership remains alive during asynchronous shutdown and range reads. Quota is released with the underlying storage lifetime.
Default builds retain their existing scheduling policy. Unsupported legacy paths reject explicitly configured resources.

## Resource contract

The memory limit applies to documented reservations and admission estimates. It does not cap process RSS.
Model training, HNSW graphs, unadmitted upstream/current input, and file codec transients remain outside those reservations.
Partition estimates account for known conversion and remapping work; they are not allocator measurements.

A single batch or partition can exceed the minimum supported working set. This branch does not silently bypass an explicit pool limit.
It does not automatically retrain or repartition an index to make every possible input succeed.
External consumers can exhaust a shared pool. The current scheduler reports exhaustion when it has no owned work that can release capacity.

## Issue scope

The branch addresses [#7305](https://github.com/lance-format/lance/issues/7305) and [#7308](https://github.com/lance-format/lance/issues/7308).
Current main already writes completed partitions directly to final index files.
The implementation therefore controls existing shuffle scratch and partition admission on the current builder path.
It does not serialize an in-progress subindex or add an all-in-memory shuffle path.
Those exclusions prevent a claim that all historical parent-issue goals are complete.

## Delivery status

The two implementation commits are on the user's fork branch `codex/ivf-build-memory-spill`.
This directory adds review reports and evidence. No upstream PR has been created for this candidate in this task.
The [validation report](validation-report.md) records targeted tests and full workspace Clippy.
The [resource report](resource-report.md) records diagnostic results without an optimized throughput claim.
