# Exact 4.5 GB writer benchmark

Baseline `cb8c25692` and final `d0020f429`, Lance file format 2.2. The separately built executables each completed one warmup and three interleaved measured trials. Each trial made one writer batch call with 25,000 distinct 180,000-byte LargeBinary values. Every full scan and 128-row random take verified the returned values against the input. Both builds reported the same full input fingerprint, `b4dc1a344606207d`, and the same take indices.

| Metric | Upstream | Final |
| --- | ---: | ---: |
| File bytes | 103,950,079 | 103,969,834 |
| FullZip pages | 1 | 135 |
| Largest uncompressed value payload per page, bytes | 4,500,000,000 | 33,480,000 |
| Largest encoded page, bytes | 103,949,748 | 773,392 |
| Write wall seconds, median [min, max] | 0.203375 [0.191388, 0.207335] | 0.177324 [0.161410, 0.179821] |
| Write process CPU seconds, median [min, max] | 0.758884 [0.756901, 0.776261] | 1.055540 [1.052799, 1.067854] |
| Write average cores, median [min, max] | 3.7440 [3.7315, 3.9548] | 5.9526 [5.9384, 6.5225] |
| Streaming scan seconds, median [min, max] | 0.629764 [0.617870, 0.659794] | 0.502074 [0.483790, 0.505988] |
| Random take seconds, median [min, max] | 0.006328 [0.006012, 0.007399] | 0.005323 [0.004899, 0.005665] |

The file grew by 19,755 bytes (0.019%). Median write wall time fell 12.8% in these runs while process CPU rose 39.1%. Scan time includes row comparisons, which took roughly 0.28–0.41 seconds across the measured trials. Reads reused the local file after write and take followed the full scan. The warmup reads spanned a wider timing range. With three trials, a highly compressible input, and earlier observations of around 10% timing variation in this workflow, the wall-time numbers characterize this run only.

Memory pressure remained normal and swap usage was zero in every sampled interval. The largest observed RSS across the two warmups and six measured trials was 5,472,512 KiB. RSS was sampled once per second across generation, write, and reads, so it can miss short peaks.

[Measured rows](measurements.tsv) · [Harness](writer10526.rs) · [Commands](benchmark.sh) · [Host and toolchain](machine.txt)
