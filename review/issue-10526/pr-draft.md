# fix(encoding): split oversized pages of wide variable-width values

A single batch of wide variable-width values can produce an oversized page in the 2.1+ structural writer. The dense page planner does not apply `max_page_bytes` to that batch.

Dense planning can now split at value boundaries after rep/def serialization. The rep/def budget must permit the split. Each row must map to one string or binary value, and the field must use the default layout or request FullZip. The planner requires at least two values whose total uncompressed value bytes exceed the page limit. It uses proportional boundaries when they fit in the same number of pages as greedy packing.

The planner requires at least one valid slot, and every valid slot must exceed 32 KiB. A null slot must be empty or exceed 32 KiB. The planner samples non-empty physical slots, including payloads under nulls, because the dictionary encoder interns them.

For a dictionary limit of `D` bytes, the planner samples up to `floor(D / 32,769) + 1` non-empty physical slots. Each non-empty entry uses at least 32,769 bytes. A dictionary that fits holds at most one fewer distinct non-empty entry, so a full sample must contain a repeat. An average-width rule would not establish this bound.

The planner also samples the same number of valid slots, up to the number available, to detect constant values. It hashes the full payload of each slot in the union once. A repeated key keeps the batch unsplit.

This change leaves 2.3 sparse pages for mostly-null wide columns, mixed-width batches, lists, and fixed-width values on their existing paths. It preserves the file format.

Mixed-width batches can still produce oversized pages.

PR #10531 parallelizes compression within a page and complements parallel work across pages. [#10531](https://github.com/lance-format/lance/pull/10531)

Reader-side chunking remains necessary for existing files and pages that stay unsplit. [#10160](https://github.com/lance-format/lance/pull/10160) · [#10168](https://github.com/lance-format/lance/pull/10168)

## Measurements

A separate probe at `8d39b38` used fixed-seed random payloads under nulls. At 16 MiB, both 2.1 and 2.2 wrote three pages totaling 8,364,434 encoded bytes. At `u64::MAX`, each version wrote one page. Version 2.1 wrote 8,359,337 encoded bytes, and 2.2 wrote 8,391,350. Splitting added 5,097 encoded bytes in 2.1 and saved 26,916 in 2.2.

The tables compare baseline `b4fb0936d` with fix `d47fe89d8`. Both builds used `release-with-debug` and the same Arrow IPC inputs on a 16-vCPU host. The 32 MiB limit compares uncompressed value bytes. The largest resulting compressed page was about 11 MB on the unique-wide input. The write matrix reports medians of three trials. [Method and raw results](https://github.com/easyrev/lance/blob/review/10526-wide-value-page-split/review/issue-10526/README.md)

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
| 1 | 8 | baseline | 1.035 | 2,543,760 | 1,555,160 | 988,600 |
| 1 | 8 | fix | 0.787 | 2,182,416 | 1,554,832 | 627,584 |
| 1 | 16 | baseline | 0.892 | 2,549,548 | 1,554,924 | 994,548 |
| 1 | 16 | fix | 0.627 | 2,237,864 | 1,555,024 | 682,804 |
| 8 | 8 | baseline | 7.712 | 15,334,420 | 11,420,424 | 3,914,024 |
| 8 | 8 | fix | 5.474 | 15,374,816 | 11,420,560 | 3,954,276 |
| 8 | 16 | baseline | 4.614 | 18,126,624 | 11,420,412 | 6,706,108 |
| 8 | 16 | fix | 4.238 | 15,445,576 | 11,420,288 | 4,025,288 |

Closes #10526
