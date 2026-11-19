# fix(encoding): split oversized pages of wide variable-width values

A single batch of wide variable-width values can produce an oversized page in the 2.1+ structural writer. The dense page planner does not apply `max_page_bytes` to that batch.

Dense planning can now split at value boundaries after rep/def serialization. The rep/def budget must permit the split. Each row must map to one string or binary value, and the field must use the default layout or request FullZip. The planner requires at least two values whose total uncompressed value bytes exceed the page limit. It uses proportional boundaries when they fit in the same number of pages as greedy packing.

The planner requires at least one non-null value and requires every non-null value to exceed 32 KiB. It samples evenly across non-null values. For a dictionary limit of `D` bytes, it samples up to `floor(D / 32,769) + 1` values. A dictionary that fits in `D` bytes can hold at most one fewer distinct value, because every value takes at least 32,769 bytes. If the batch has at least that many non-null values, a dictionary-eligible input must repeat a sampled key. If fewer exist, the planner samples every non-null value and detects any repetition among them. The existing plan is also preserved when a single page suffices. An average-width rule would not give the same bound on dictionary cardinality.

This change leaves 2.3 sparse pages for mostly-null wide columns, mixed-width batches, lists, and fixed-width values on their existing paths. It preserves the file format.

PR #10531 parallelizes compression within a page and complements parallel work across pages. [#10531](https://github.com/lance-format/lance/pull/10531)

Reader-side chunking remains necessary for existing files and pages that stay unsplit. [#10160](https://github.com/lance-format/lance/pull/10160) · [#10168](https://github.com/lance-format/lance/pull/10168)

## Measurements

Both builds used `release-with-debug` and reused the same Arrow IPC inputs on a 16-vCPU host. The 32 MiB limit compares uncompressed value bytes. The largest resulting compressed page was about 11 MB on the unique-wide input. The write matrix reports medians of three trials. [Method and raw results](https://github.com/easyrev/lance/blob/review/10526-wide-value-page-split/review/issue-10526/README.md)

### Table A. Files

| Input | Build | File B | Pages | Max encoded page B | Max uncompressed value B |
| --- | --- | ---: | ---: | ---: | ---: |
| wide-unique | baseline | 491,127,295 | 1 | 491,126,941 | 1,440,000,000 |
| wide-unique | fix | 491,134,489 | 44 | 11,175,002 | 32,760,000 |
| wide-repeated | baseline | 491,019,071 | 1 | 491,018,724 | 1,440,000,000 |
| wide-repeated | fix | 491,019,071 | 1 | 491,018,724 | 1,440,000,000 |
| narrow | baseline | 28,099,756 | 1 | 28,099,448 | 80,000,000 |
| narrow | fix | 28,099,756 | 1 | 28,099,448 | 80,000,000 |

### Table B. Median of three writes

| Writers | CPU threads | Build | Write s | Peak RSS KiB | Pre-write RSS KiB | Peak minus pre-write KiB |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 8 | baseline | 1.066 | 2,543,916 | 1,555,236 | 988,680 |
| 1 | 8 | fix | 0.771 | 2,166,412 | 1,554,892 | 611,520 |
| 1 | 16 | baseline | 0.909 | 2,549,660 | 1,555,004 | 994,656 |
| 1 | 16 | fix | 0.616 | 2,230,132 | 1,555,020 | 675,184 |
| 8 | 8 | baseline | 7.632 | 15,160,568 | 11,420,540 | 3,739,816 |
| 8 | 8 | fix | 5.280 | 15,373,640 | 11,420,512 | 3,953,004 |
| 8 | 16 | baseline | 4.457 | 17,646,804 | 11,420,408 | 6,226,520 |
| 8 | 16 | fix | 4.153 | 15,451,316 | 11,420,436 | 4,030,860 |

Closes #10526
