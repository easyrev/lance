# Random take after wide-value page splitting

The additional latency is inside `dataset.take()`. For a fresh dataset handle and 128 random rows, open was 3.85 → 3.98 ms and take was 28.38 → 41.12 ms (upstream → final). The final build reproduced the upstream timing when it wrote the same input as one page.

## Method

Debian 13.7, AMD EPYC 9T24, 64 vCPUs and `LANCE_CPU_THREADS=64`. Both `release-with-debug` extensions and the 25,000-row `wide-unique` IPC input were reused from the [original benchmark](README.md). Both input and output were on tmpfs. The original input SHA-256 and the two extension SHA-256 values are in [the benchmark records](raw/). Each row is a distinct 180,000-byte LargeUtf8 value. The row sample was sorted after NumPy sampling without replacement, seed 10526. Within a sample size we reused exactly the same indices across files. Every headline timing is a fresh Python process, one open and one take, with Python import and index generation outside the timers. Five trials per cell. Values are median [min–max] in milliseconds.

## Varying rows at the default page budget

| Rows | Upstream open, 1 page | Final open, 135 pages | Upstream take | Final take | Take delta |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.99 [3.77–4.07] | 3.85 [3.76–4.05] | 1.46 [1.42–1.48] | 1.68 [1.65–1.70] | +0.22 |
| 16 | 3.99 [3.96–4.02] | 3.90 [3.84–4.09] | 6.25 [6.13–6.41] | 7.80 [7.64–7.87] | +1.55 |
| 128 | 3.85 [3.83–4.00] | 3.98 [3.91–4.01] | 28.38 [27.96–29.03] | 41.12 [40.77–41.35] | +12.74 |
| 1024 | 3.87 [3.78–4.03] | 3.89 [3.83–3.94] | 199.91 [199.17–200.66] | 305.46 [302.62–306.40] | +105.55 |

## Varying pages at 128 rows

All five files were written and read with the final build on the same 25,000 rows. The cap was set with `LANCE_FILE_WRITER_MAX_PAGE_BYTES`. The file footer confirmed each exact page count. The syscall columns are counts and bytes returned by `pread64` against the fragment’s `.lance` file in one separate traced process per case. They include the initial file-metadata read inside take. Trace timings are excluded from the medians.

| Pages | Cap (bytes) | Pages touched | Open | Take | Fragment reads | Fragment bytes returned |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4,500,000,000 | 1 | 4.03 [3.85–4.04] | 28.37 [28.30–28.52] | 129 | 7,961,823 |
| 2 | 2,250,000,000 | 2 | 3.86 [3.82–4.08] | 33.72 [33.58–34.07] | 130 | 7,961,827 |
| 8 | 562,500,000 | 8 | 3.93 [3.87–4.04] | 42.04 [41.38–42.68] | 136 | 7,961,851 |
| 44 | 102,420,000 | 44 | 3.98 [3.84–4.13] | 41.20 [40.67–41.29] | 173 | 7,962,454 |
| 135 | 33,480,000 | 82 | 4.00 [3.87–4.12] | 41.33 [41.28–41.83] | 211 | 7,932,441 |

## Where the time goes

- **First-use page-index I/O and scheduling.** FullZip must locate the compressed byte ranges before it can fetch the requested values. On the 135-page file the first take visited 82 pages. The trace showed 82 small page-index reads (744–748 bytes each), while total bytes read remained about 8 MB. A second take on the same open handle issued 127 fragment reads in both layouts. In five fresh processes per layout, pairing a first and second take, the medians were **28.35 → 26.05 ms** for one page and **41.11 → 34.00 ms** for 135 pages. The gap fell from 12.76 to 7.95 ms, a roughly 4.8 ms difference of differences for first-use work in this test. This measures a cache effect and does not isolate index I/O from other first-use costs.
- **Per-value decode and multi-page result assembly.** Take-only CPU-clock sampling at 499 Hz covered 35 repeated takes after open, for one page and 135 pages. It recorded 426 and 479 samples respectively, with zero reported lost samples. Both profiles were dominated by `ZSTD_decompressSequences_bmi2` inside `VariableFullZipDecodeTask` (68.08% and 65.76% self). Only the multi-page graph showed `concat_decoded_arrays → arrow_select::concat::concat_bytes` above the reporting threshold (5.43% inclusive). It combines decoded page arrays into one output. With 128 wide rows that output contains 23.04 MB of value bytes. The extra copy/assembly work scales with the bytes selected once results span multiple pages. The profile establishes that this work occurs and accounts for some CPU time. It does not attribute the entire remaining wall-time gap to copying or measure off-CPU waits.
- **Scaling.** At 128 rows the cost grows from one to two to eight pages and then levels off through 135, despite the touched pages rising from 8 to 82. The extra work is neither a fixed open cost nor a constant per-page wall-time penalty. The default-layout take delta grew from 0.22 ms for one row to 12.74 ms for 128 and 105.55 ms for 1,024, consistent with selected-byte-dependent work plus first-use index/scheduler costs. These runs do not identify a universal saturation point.

The source paths are `FullZipScheduler::{init_layout,schedule_ranges_rep}` in `rust/lance-encoding/src/encodings/logical/primitive/fullzip_decode.rs` and `StructuralCompositeDecodeArrayTask::decode` in `rust/lance-encoding/src/encodings/logical/primitive/field.rs`, both at final commit `d0020f429`.

## Object-storage inference

The first take can pay more latency on object storage. The extra small index reads may become separate range GETs, and the payload offsets depend on those reads. Concurrency and coalescing can overlap requests, so multiplying the local delta or the request count by one RTT would not predict wall time. The additional index phase and any queueing/request waves are likely to matter more than the near-identical payload byte totals. Reusing the handle/session can avoid cached index requests. Decompression and result assembly still happen on the reader. The object-store request count, concurrency and latency were not measured, so the local 8–135-page plateau should not be assumed remotely.

[Raw timing, metadata, syscall and CPU reports](take-investigation/raw/) · [Timing harness](take-investigation/take.py) · [Profile commands](take-investigation/profile.sh)

The syscall logs and perf symbol reports are archived as gzip files.

The three diagnostic runs (syscall trace, Lance trace and CPU sampling) were separate from headline timings. The first perf launch captured samples but its end-of-run acknowledgment check failed. The next run was interrupted during report rendering when inline symbol resolution stalled. The archived reports use the final rerun with `--no-inline`; function symbols and call chains are retained.
