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

The regression cases cover a valid empty value alongside dirty null payloads, dictionary budget boundaries, configured entry limits, and contiguous repeats with round-trip decoding. On an Apple Silicon Mac, one format 2.2 writer call with 25,000 distinct 180,000-byte LargeBinary values went from one 4.5 GB raw FullZip page to 135 pages with a maximum raw payload of 33.48 MB. The file grew 0.019%, and all full scans and seeded random takes matched the original input.

Across three interleaved measured trials, median write wall time went from 203 ms to 177 ms and process CPU time from 759 ms to 1,056 ms. Warm local scan and take medians were 630 to 502 ms and 6.33 to 5.32 ms. These timings use one compressible input on one machine. [Measurement details](benchmark-results.md)

The complete lance-encoding and lance-file suites, Python file tests, Rust formatting, and Python lint passed. The strict workspace Rust Clippy command reports two pre-existing unreachable expressions in the Arm64 byte-stream-split code on this Mac. [Verification details](verification-results.md)

## Merge Danger

**Door** Two-way.

**Blast radius** Structural writes of flat UTF-8 and binary values with a wide value and an oversized batch. Page boundaries can change. The file format is unchanged.

Refs #10526
