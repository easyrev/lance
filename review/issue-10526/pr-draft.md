# perf(encoding): split oversized pages of wide variable-width values

## Summary

The structural writer can send a batch of wide values to one FullZip page even when its uncompressed values exceed the requested page size.

```text
eligible dense string/binary batch
  sample physical dictionary bytes and compare valid values
  on a split decision, partition at row boundaries
  encode the resulting pages through the existing structural writer
```

The split requires evidence of two different logical values. Empty valid values can supply that evidence, and payloads under nulls only affect the physical dictionary check. The planner requires a sampled distinct-byte lower bound above the configured dictionary budget, or a page budget below the dictionary budget, full coverage of distinct non-empty physical values, and a count above the dictionary's entry limit. The probe is bounded by the dictionary budget. Batches dominated by 31,000-byte values can still stay oversized, and logically constant batches can pay the probe cost before retaining a single page.

## Evidence

On Debian 13.7 with an AMD EPYC 9T24, 64 vCPUs (32 cores with two threads each) and 247 GiB of OS-visible RAM, we compared upstream `cb8c25692` with `d0020f429` using independent `release-with-debug` builds. The format 2.2 inputs reuse the November 18 generator. Each wide LargeUtf8 value is 180,000 bytes and combines a row ID with draws from 4,096 randomly generated words. The suite varies cardinality, repetition, and the presence of short, empty, and null values, and includes an int64 control. Both builds exactly reproduced the input rows for every dataset.

The 25,000-distinct case went from 1 to 135 pages. Maximum logical page payload went from 4.50 GB to 33.48 MB, and file size changed by +0.001%. With contiguous repeats, the clustered file shrank from 1.534 GB to 29.51 MB across 90 constant pages and 45 dictionary-encoded pages. The 10-value, constant and int64 controls retained their exact file sizes and page counts.

For 8 writers at 8 Lance CPU threads, the median across three measured runs was 9.067 s → 6.284 s wall time, 50.078 s → 50.306 s process CPU, and 7,059 → 10,184 rows/s. All file-size, write-wall, and write-RSS comparisons met their limits. Five read RSS comparisons exceeded the 10% limit (wide-unique-8k scan, wide-repeated scan, wide-repeated take, wide-clustered scan, wide-clustered take). The summary includes the full write matrix, scan and take results, and raw observations. [Linux results](linux-64cpu/summary.md)

On the earlier Mac validation, the complete lance-encoding and lance-file suites, Python file tests, Rust formatting, and Python lint passed. The strict workspace Rust Clippy command reports two pre-existing unreachable expressions in the Arm64 byte-stream-split code on that host. [Verification details](issue-scale/verification-results.md)

## Merge Danger

**Door** Two-way.

**Blast radius** Structural writes of flat UTF-8 and binary values with a wide value and an oversized batch. Page boundaries can change. The file format is unchanged.

Refs #10526
