# Native source scan defaults

## Decision

No effective default differs between the Python scanner path and `LanceTableProvider`.
I made no code change, no fixup commit, and no follow-up benchmark run.
Commit 2 remains `9767241c21d4124dc2f8d24d642abe93c8ca859c`.

The PR tree is clean.

## Effective settings

The local object store has a 4 KiB block size and 8 I/O threads.
The host has 16 CPUs, and Lance reserves 2 CPUs for I/O.
I found no `LANCE_*` environment override.

| Setting | Python scanner request | Python effective | Native provider request | Native effective | Same |
|---|---|---|---|---|---|
| Row batch size | `None` | 8,192 rows | `None` | 8,192 rows | Yes |
| Byte batch size | `None` | `None` | `None` | `None` | Yes |
| I/O buffer size | `None` | 2 GiB | `None` | 2 GiB | Yes |
| Fragment readahead | `None` | 16 fragments for v2, 4 for v1 | `None` | 16 fragments for v2, 4 for v1 | Yes |
| Batch readahead | `None` | 14 batches | `None` | 14 batches | Yes |
| Scan order | `True` | Ordered | `True` | Ordered | Yes |

The Python `ScannerBuilder` stores `None` for all five scan knobs.
`to_scanner()` passes those values to the Rust binding.
The binding calls the matching scanner setters only for non-`None` values.

`Scanner::new()` then supplies these Rust defaults:

- `batch_size=None`
- `batch_size_bytes=None`
- `io_buffer_size=None`
- `batch_readahead=14`
- `fragment_readahead=None`

The v2 scan resolves `fragment_readahead` from `io_parallelism * 2`.
The local store has `io_parallelism=8`, which resolves to 16.

`get_batch_size()` resolves local scans to `max(4096 / 4, 8192)`, which is 8,192 rows.
The source plan emitted 676 batches for 5,534,750 rows, or about 8,188 rows per batch.
P1 and P2 both emitted the same 676 source batches.

## Why P2 uses more memory

The scan settings are equal.
The difference appears above the scan layer:

- P1 exposes a one-partition `StreamingTableExec` from a Python `RecordBatchReader`.
- P2 exposes `LanceRead` directly inside the DataFusion merge plan.
- Both feed a 16-way `RepartitionExec`.
- The analyzed P1 source fetch time was 1.56 s.
- The analyzed P2 source fetch time was 14.62 s.

Cold-cache measurements also reject extra physical I/O parallelism:

- P1 read 15.96 GiB at 0.0978 GiB/s.
- P2 read 15.96 GiB at 0.0965 GiB/s.
- P1 used 30.429 s CPU and P2 used 30.638 s CPU.

The extra RSS is consistent with DataFusion exchange and buffering behavior above the native provider.
The evidence does not support a scan-default mismatch.

A diagnostic local build with `with_batch_size_bytes(64 MiB)` reduced P2 RSS, but 64 MiB is a new constant.
It is not an existing Python-scanner default, so I did not apply or commit it.

## Conditional tests

I did not run the requested cold-cache confirmation tables.
Step 2 says to stop when no default differs, so the fixup and confirmation runs are not applicable.

## Source references

- Python scanner defaults: `python/python/lance/dataset.py`
- Python-to-Rust scanner binding: `python/src/dataset.rs`
- Rust scanner defaults: `rust/lance/src/dataset/scanner.rs`
- Native provider: `rust/lance/src/datafusion/dataframe.rs`
- Native source provider: `rust/lance/src/dataset/write/merge_insert.rs`
- V2 scan readahead resolution: `rust/lance/src/io/exec/scan.rs`
