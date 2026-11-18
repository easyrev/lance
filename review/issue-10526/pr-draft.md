# fix(encoding): split oversized pages of wide variable-width values

A single batch of wide variable-width values can produce an oversized page in the 2.1+ structural writer. The dense page planner does not apply `max_page_bytes` to that batch. [Issue #10526](https://github.com/lance-format/lance/issues/10526)

After rep/def serialization, dense planning can split at value boundaries for the default layout or an explicit FullZip request. The rep/def budget must permit splitting, each row must map to a single string or binary value, and at least two values must exceed the configured page limit in aggregate. At least one value must be non-null, every non-null value must exceed the per-value compression threshold, and the sampled value fingerprints must be distinct. The planner balances page sizes and retains row order.

Narrow columns, repeated wide values detected by the sample, and lists continue through the existing planning path. Pages use the existing file format. The scope is dense write-time planning for wide values. Reader-side handling of existing large pages and splitting fixed-width or list columns are follow-up work.

## Measurements

Measured with two local Python builds using `release-with-debug` and the same Arrow IPC inputs on a 16-vCPU host. The write matrix reports medians of three trials. [Method and raw results](README.md)

### Table A. Files

| Input | Baseline file B | Pages | Max page B | Fix file B | Pages | Max page B |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| wide-unique | 491,127,295 | 1 | 491,126,941 | 491,133,910 | 44 | 11,420,339 |
| wide-repeated | 491,019,071 | 1 | 491,018,724 | 491,019,071 | 1 | 491,018,724 |
| narrow | 28,099,756 | 1 | 28,099,448 | 28,099,756 | 1 | 28,099,448 |

### Table B. Median of three writes

| Writers | CPU threads | Build | Write s | Peak RSS KiB | Pre-write RSS KiB | Peak minus pre-write KiB |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 8 | baseline | 1.039 | 2,542,868 | 1,555,032 | 987,884 |
| 1 | 8 | fix | 0.750 | 2,179,668 | 1,555,188 | 624,480 |
| 1 | 16 | baseline | 0.877 | 2,548,720 | 1,555,084 | 993,636 |
| 1 | 16 | fix | 0.627 | 2,248,620 | 1,555,124 | 693,436 |
| 8 | 8 | baseline | 7.628 | 15,171,140 | 11,420,404 | 3,750,772 |
| 8 | 8 | fix | 5.271 | 15,378,688 | 11,420,416 | 3,958,176 |
| 8 | 16 | baseline | 4.490 | 17,928,908 | 11,420,628 | 6,508,280 |
| 8 | 16 | fix | 4.174 | 15,449,288 | 11,420,516 | 4,028,540 |

- 1 writer(s), 8 CPU threads, peak RSS ratio 0.8572. Pass.
- 1 writer(s), 16 CPU threads, peak RSS ratio 0.8823. Pass.
- 8 writer(s), 8 CPU threads, peak RSS ratio 1.0137. Pass.
- 8 writers, 8 CPU threads, wall-time ratio 0.6910. Pass.
- 8 writer(s), 16 CPU threads, peak RSS ratio 0.8617. Pass.
