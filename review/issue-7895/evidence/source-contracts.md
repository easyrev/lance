# Independently verified source contracts

Baseline: official `lance-format/lance` main at
`4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9`. This note records source inspection,
not dynamic test results. It predates the permitted Phase 1 comparison.

## Requested behavior

- [Issue #7895](https://github.com/lance-format/lance/issues/7895) couples a
  `singledispatch` source registry with a provider that can repeat a source scan.
  The purpose is to avoid the replay buffer for suitable Python inputs.
- [Maintainer review](https://github.com/lance-format/lance/pull/7368#discussion_r3587879253)
  identifies classifier drift and omitted Lance scanners, Lance datasets, and
  Arrow datasets.
- [Author response](https://github.com/lance-format/lance/pull/7368#discussion_r3625757669)
  rejects full materialization merely to avoid spilling and proposes the registry
  plus repeatable scans.
- [Retry clarification](https://github.com/lance-format/lance/pull/7368#discussion_r3625757790)
  states that one-shot sources buffer only when `conflict_retries > 0`.
  Providers that can repeat a scan bypass this buffer.

## Lance snapshot and ordering

- [Python native scanner](https://github.com/lance-format/lance/blob/4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9/python/src/scanner.rs#L36)
  owns `Arc<LanceScanner>`. Its `to_pyarrow` clones this scanner for each reader.
  Reusing this object retains the native dataset version and scan settings.
- [Default scan options](https://github.com/lance-format/lance/blob/4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9/python/python/lance/dataset.py#L1499)
  apply to `LanceDataset.scanner()`. A dataset can therefore carry filters,
  computed projections, searches, ordering, and other nondefault settings.
  Dataset type alone does not establish stable repeated results.
- [Scan ordering](https://github.com/lance-format/lance/blob/4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9/rust/lance/src/dataset/scanner.rs#L2245)
  permits out-of-order results when `scan_in_order` is false. Explicit sorting
  ignores that flag. Equal sort keys do not establish a unique row order.
- [FirstSeen merge behavior](https://github.com/lance-format/lance/blob/4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9/rust/lance/src/dataset/write/merge_insert.rs#L2511)
  deduplicates in source order before the join. Repeated scans must retain the
  same winner for duplicate keys, not merely the same set of rows.
- [Expression simplification](https://github.com/lance-format/lance/blob/4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9/rust/lance-datafusion/src/planner.rs#L1062)
  supplies the current query start time. Checking only optimized expressions can
  miss time-dependent expressions that already became literals.
- [Reader runtime handling](https://github.com/lance-format/lance/blob/4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9/python/src/reader.rs#L147)
  uses `block_in_place` when a synchronous reader waits on a Tokio worker.
  A Python reader factory can itself call Lance and wait on that runtime.
  New factory calls therefore need a blocking-safe execution path.

## PyArrow API boundaries

The project supports `pyarrow>=14`. The following behavior appears in both
[Arrow 14 source](https://github.com/apache/arrow/blob/apache-arrow-14.0.0/python/pyarrow/_dataset.pyx)
and the inspected
[Arrow main source](https://github.com/apache/arrow/blob/main/python/pyarrow/_dataset.pyx).

- `Scanner.from_batches` explicitly creates a scanner that can be used only
  once. Python exposes no public scanner capability query or underlying dataset
  accessor. Repeated `to_reader()` calls are therefore unsafe as a type-wide rule.
- `Dataset.filter` preserves the filter in `_scan_options`.
  `Scanner.from_dataset` applies these options. Reconstructing a source from its
  fragments can lose these semantics.
- Public `Dataset.get_fragments()` rejects a filtered dataset before returning
  its iterator. This check requires no iteration and consumes no source rows.
  It supports conservative qualification of unfiltered built-in dataset types.
- `InMemoryDataset` constructs its native table from its accepted input.
  `FileSystemDataset` retains a fixed collection of file fragments.
  `UnionDataset.children` exposes its children for recursive qualification.
  Custom subclasses do not inherit a proven replay contract merely from their
  base class.
- Fixed file fragments do not pin file contents. Arrow file sources must remain
  unchanged throughout the operation. A replay adapter cannot infer external
  file immutability or stabilize an arbitrary custom filesystem.
- The [C++ Scanner contract](https://github.com/apache/arrow/blob/main/cpp/src/arrow/dataset/scanner.h#L418)
  says `ScanBatches` returns batches in dataset fragment order. Unordered scanning
  uses a separate API.
- [Arrow random](https://github.com/apache/arrow/blob/main/cpp/src/arrow/compute/kernels/scalar_random.cc#L90)
  is a scalar function marked `is_pure=false`. The Python expression API permits
  scalar calls. A filter's mere presence does not prove stable repeated values.
- [Python scalar UDF contract](https://github.com/apache/arrow/blob/main/python/pyarrow/_compute.pyx#L3138)
  requires stateless elementwise behavior. Python exposes no general public
  expression purity inspection API. Conservative fallback avoids relying on
  expression text or private Arrow internals.

## Candidate consequences

The registry returns an executable reader factory and an explicit strategy.
Automatic replay qualifies ordered native scans with known stable settings and
unfiltered built-in Arrow datasets. Other sources retain their original reader
path. Explicit third-party adapters can promise stable schema, values, order,
fresh readers, and an immutable or version-pinned source.

The normal reader conversion uses the same registry but consumes one reader.
Merge execution and data-based analysis use the same strategy. Schema-only
`explain_plan` retains its documented streaming-shape meaning.

The factory contract permits worker-thread and overlapping calls. Cancellation
cannot interrupt a Python callback before it returns. Returned readers remain
owned by the operation and must be released when execution ends.
