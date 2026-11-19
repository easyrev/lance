# fix(encoding): split oversized pages of wide variable-width values

A single batch of wide variable-width values can produce an oversized page in the 2.1+ structural writer. The dense page planner does not apply `max_page_bytes` to that batch.

After rep/def serialization, dense planning can split at value boundaries for the default layout or an explicit FullZip request. The rep/def budget must permit splitting, each row must map to a single string or binary value, and at least two values must exceed the configured limit in aggregate. At least one value must be non-null, every non-null value must exceed the per-value compression threshold, and the sampled value fingerprints must be distinct. The planner uses proportional boundaries when they fit in the same number of pages as greedy packing at the limit.

Narrow columns, sampled duplicate wide values, and lists continue through existing planning. The pages use the existing file format. Write-time limits for fixed-width and list columns are follow-up work.

[#10531](https://github.com/lance-format/lance/pull/10531) parallelizes compression within a page and complements parallel work across pages.

The reader-side chunking proposed in [#10160](https://github.com/lance-format/lance/pull/10160) and [#10168](https://github.com/lance-format/lance/pull/10168) is still needed for existing files and pages that remain unsplit.

## Measurements

Both builds used `release-with-debug` and reused the same Arrow IPC inputs on a 16-vCPU host. The 32 MiB limit applies to uncompressed value bytes and produced compressed pages of about 11 MB on the unique-wide input. The write matrix reports medians of three trials. [Method and raw results](https://github.com/easyrev/lance/blob/review/10526-wide-value-page-split/review/issue-10526/README.md)

### Table A. Files

| Input | Baseline file B | Pages | Max page B | Fix file B | Pages | Max page B |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| wide-unique | 491,127,295 | 1 | 491,126,941 | 491,134,489 | 44 | 11,175,002 |
| wide-repeated | 491,019,071 | 1 | 491,018,724 | 491,019,071 | 1 | 491,018,724 |
| narrow | 28,099,756 | 1 | 28,099,448 | 28,099,756 | 1 | 28,099,448 |

### Table B. Median of three writes

| Writers | CPU threads | Build | Write s | Peak RSS KiB | Pre-write RSS KiB | Peak minus pre-write KiB |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 8 | baseline | 1.028 | 2,543,052 | 1,555,244 | 987,828 |
| 1 | 8 | fix | 0.755 | 2,179,172 | 1,554,912 | 624,460 |
| 1 | 16 | baseline | 0.890 | 2,548,912 | 1,555,048 | 993,876 |
| 1 | 16 | fix | 0.594 | 2,237,360 | 1,555,060 | 682,300 |
| 8 | 8 | baseline | 7.624 | 15,225,372 | 11,420,432 | 3,804,768 |
| 8 | 8 | fix | 5.282 | 15,355,608 | 11,420,468 | 3,935,440 |
| 8 | 16 | baseline | 4.433 | 17,727,232 | 11,420,452 | 6,306,452 |
| 8 | 16 | fix | 4.143 | 15,440,248 | 11,420,576 | 4,019,672 |

Closes #10526
