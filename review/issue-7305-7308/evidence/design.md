# IVF build resource controls

Branch: `easyrev/lance:codex/ivf-build-memory-spill`
Base: `08ea2c11674daf4791a00388b0bbe4bd9b339121`
Published head: `09d2c8a0d`
Commits: `dd95988d4` (spill lifetime/quota), `09d2c8a0d` (IVF resource controls)
Remote branch: https://github.com/easyrev/lance/tree/codex/ivf-build-memory-spill

## Scope and decisions

- Add caller-owned DataFusion MemoryPool options to CreateIndexBuilder and OptimizeOptions. Preserve default behavior.
- Use one pool for shuffle accumulation, optional offsets, partition admission, and completed results awaiting writes.
- Flush under pressure, reduce admission, then release optional offsets before rejecting a minimum working set.
- A supplied pool may reject an unspillable input batch or partition. Do not silently bypass its limit or retrain/repartition the index.
- Session SpillStore owns shuffle data, offsets, and page-metadata scratch. Current main writes completed partition results directly to final files.
- Preserve the legacy-shuffler switch when neither pool nor custom store is configured. Reject explicit resources on unsupported legacy paths.
- These reservations do not bound process RSS. Training, HNSW graphs, upstream/current input batches, and file encoder/decoder transients remain outside the accounting.
- Do not claim an all-in-memory fast path or arbitrary-size partition completion. The current two-file shuffle remains the scratch codec.

## Design evidence

- https://github.com/lance-format/lance/issues/7305 — pool-controlled shuffle batches and partition construction.
- https://github.com/lance-format/lance/issues/7308 — reclaimable shuffle/partition scratch.
- https://github.com/lance-format/lance/issues/7301 — reactive spilling, HNSW excluded.
- https://github.com/lance-format/lance/issues/9799 — caller chooses pool capacity and sharing, unset preserves behavior.
- https://github.com/lance-format/lance/pull/7314 — same author flushes under pressure, rejects one document that cannot fit an empty pool. Unmerged precedent, not maintainer approval of this IVF policy.
- https://github.com/lance-format/lance/pull/7295#discussion_r3443347478 — avoid copying already-loaded large batches just to split them.
- https://github.com/lance-format/lance/pull/7295#issuecomment-4723172945 — large offline IVF_PQ workload, 2–8 GB shuffle batches reduce flush groups; k-means dominates total peak.
- https://github.com/lance-format/lance/pull/9434 — large offset tables matter for read efficiency; single warm-cache replay does not establish general speedup.

## Validation so far

- `lance-io` spill tests: 19 passed.
- Latest full `lance-index` shuffle suite: 56 passed.
- `lance-file` metadata spill tests: 4 passed.
- Shuffle resource diagnostic: all six combinations passed exact row/vector validation (262,144 x 64 Float32 vectors; uniform/hotspot; unbounded, 8 MiB, 32 MiB).
- Both distributions: 8 MiB produced 32 flush groups; 32 MiB produced 8 groups. Peak reservations were 4,541,824 and 18,101,248 bytes respectively. Every run released all reservations and spill handles.
- Diagnostic JSON: `resource-diagnostic.jsonl`. Debug build; not a performance benchmark. Read-side verification directly reads full partitions and is not an IVF partition-admission measurement.
- Full builder suite: 29 passed, including real 4/8-bit PQ conversion and fragment reuse remapping.
- Partition scheduler: 19 passed.
- Dataset resource tests: 2 build/optimize cases (Flat/Greedy and PQ/FairSpill), 2 split/join with fragment reuse cases, 2 failure-atomicity cases, and 1 isolated legacy-switch case passed.
- Storage source ownership tests: 2 passed.
- Default vector regressions: PQ V3 (6), SQ (4), RQ (16), HNSW PQ (8), HNSW SQ (4), split/join (1), NULL (10), HNSW empty partition (1), optimize empty partition (1) passed.
- `cargo fmt --all` passed. `cargo clippy --all --tests --benches -- -D warnings` passed.
- Final input batching regressions passed: fixed vectors (8192 x 128) and multivectors (64 x 100 x 128) under a 4 MiB pool. Scan byte targets apply before decoding, including precomputed data. Split/join fetch, regroup, and route batches use the same finite-pool target.
- All affected resource tests and the full workspace Clippy command passed again after the final input batching change. Final log: `clippy-final.log`.

## Scope relative to the historical issues

Current main already writes completed partitions directly to the final index. This branch moves existing shuffle and metadata temporary files into the Session SpillStore and applies admission control to partition construction and retained results. It does not add serialization of in-progress subindex state or an all-in-memory shuffle fast path. Describe this as addressing #7305/#7308; do not assert that every parent-issue goal is closed.
