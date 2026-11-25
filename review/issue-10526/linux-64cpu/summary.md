# #10526 Linux benchmark criteria

Baseline cb8c25692 and final d0020f429, using the release-with-debug profile in separate target directories and Python environments.

- File size can grow by at most 2% per input.
- Peak process RSS can grow by at most 10% for writes, full scans and random takes.
- Write wall time can grow by at most 10% in every measured combination. Report the 8-writer, 8-thread comparison explicitly.
- Report process CPU time (user plus system during the write interval) alongside wall time.
- Use the median of the three measured repetitions separately for each metric, variant and combination. Exclude warmups. Use the single file-stage write measurement for its peak RSS comparison. Compare full-precision values and retain all trials.
- Before continuing a dataset, require an exact round trip for both builds. Require identical file size and page count for wide-low-card, wide-constant and narrow. For wide-unique, operationalize approximately 3× as compression between 2.5× and 3.5× for both files.
- Report every miss as measured.

Baseline → final. Time and RSS are medians except for single file-stage writes. Max page sizes are logical value payload bytes / sum of encoded page buffers. Per-page encoding details and all trial values are in the raw JSON.

| Case | File or timing | Peak RSS (GiB) | Other |
| --- | --- | --- | --- |
| wide-unique file | 1,534,797,507 B, 1 pages, 4,500,000,000 / 1,534,797,170 B → 1,534,818,518 B, 135 pages, 33,480,000 / 11,420,264 B | 7.263 → 6.713, -7.57% | 1,534,797,507.000 → 1,534,818,518.000, +0.00% B, exact round trips |
| wide-unique scan | 733.701 → 653.904 ms, -10.88% | 5.669 → 4.674, -17.55% | |
| wide-unique take | 32.444 → 45.427 ms, +40.02% | 0.197 → 0.215, +8.80% | |
| wide-unique-8k file | 491,127,295 B, 1 pages, 1,440,000,000 / 491,126,941 B → 491,134,489 B, 44 pages, 32,760,000 / 11,175,002 B | 2.472 → 2.518, +1.88% | 491,127,295.000 → 491,134,489.000, +0.00% B, exact round trips |
| wide-unique-8k scan | 373.747 → 366.363 ms, -1.98% | 1.999 → 2.516, +25.86% **MISS** | |
| wide-unique-8k take | 32.537 → 45.289 ms, +39.19% | 0.198 → 0.215, +8.46% | |
| wide-low-card file | 1,483,460 B, 1 pages, 4,500,000,000 / 1,483,113 B → 1,483,460 B, 1 pages, 4,500,000,000 / 1,483,113 B | 4.369 → 4.367, -0.06% | 1,483,460.000 → 1,483,460.000, +0.00% B, exact round trips |
| wide-low-card scan | 92.753 → 93.460 ms, +0.76% | 4.279 → 4.381, +2.38% | |
| wide-low-card take | 10.107 → 9.977 ms, -1.28% | 0.188 → 0.188, -0.01% | |
| wide-repeated file | 491,019,071 B, 1 pages, 1,440,000,000 / 491,018,724 B → 20,642,169 B, 44 pages, 32,760,000 / 590,474 B | 2.471 → 1.566, -36.62% | 491,019,071.000 → 20,642,169.000, -95.80% B, exact round trips |
| wide-repeated scan | 366.266 → 121.074 ms, -66.94% | 1.999 → 2.390, +19.54% **MISS** | |
| wide-repeated take | 32.093 → 44.901 ms, +39.91% | 0.198 → 0.230, +16.30% **MISS** | |
| wide-template file | 1,534,775,171 B, 1 pages, 4,500,000,000 / 1,534,774,865 B → 1,534,796,950 B, 135 pages, 33,480,000 / 11,420,152 B | 7.263 → 6.502, -10.47% | 1,534,775,171.000 → 1,534,796,950.000, +0.00% B, exact round trips |
| wide-template scan | 731.115 → 626.384 ms, -14.32% | 5.832 → 4.652, -20.24% | |
| wide-template take | 32.589 → 46.352 ms, +42.23% | 0.198 → 0.215, +8.85% | |
| wide-clustered file | 1,534,448,835 B, 1 pages, 4,500,000,000 / 1,534,448,504 B → 29,506,372 B, 135 pages, 33,480,000 / 296,514 B | 7.261 → 4.413, -39.23% | 1,534,448,835.000 → 29,506,372.000, -98.08% B, exact round trips |
| wide-clustered scan | 827.097 → 241.848 ms, -70.76% | 5.604 → 6.241, +11.36% **MISS** | |
| wide-clustered take | 32.148 → 38.885 ms, +20.96% | 0.198 → 0.232, +17.50% **MISS** | |
| wide-mixed file | 1,458,139,717 B, 1 pages, 4,275,104,000 / 1,458,139,369 B → 1,458,152,696 B, 128 pages, 33,481,560 / 11,421,839 B | 6.910 → 6.454, -6.61% | 1,458,139,717.000 → 1,458,152,696.000, +0.00% B, exact round trips |
| wide-mixed scan | 783.477 → 638.457 ms, -18.51% | 5.393 → 4.446, -17.56% | |
| wide-mixed take | 31.611 → 44.150 ms, +39.66% | 0.196 → 0.213, +8.57% | |
| wide-constant file | 180,251 B, 1 pages, 4,500,000,000 / 180,028 B → 180,251 B, 1 pages, 4,500,000,000 / 180,028 B | 4.364 → 4.365, +0.03% | 180,251.000 → 180,251.000, +0.00% B, exact round trips |
| wide-constant scan | 149.402 → 160.339 ms, +7.32% | 4.261 → 4.381, +2.82% | |
| wide-constant take | 8.966 → 8.853 ms, -1.27% | 0.187 → 0.187, -0.25% | |
| narrow file | 28,099,756 B, 1 pages, 80,000,000 / 28,099,448 B → 28,099,756 B, 1 pages, 80,000,000 / 28,099,448 B | 0.293 → 0.293, -0.02% | 28,099,756.000 → 28,099,756.000, +0.00% B, exact round trips |
| narrow scan | 128.743 → 116.960 ms, -9.15% | 0.221 → 0.221, -0.08% | |
| narrow take | 6.381 → 6.476 ms, +1.49% | 0.165 → 0.165, -0.25% | |
| wide-unique write, 1 writer(s) × 8 threads | 4.009 → 3.570 s, -10.95% | 7.221 → 6.017, -16.68% | 19.711 → 19.568 s CPU, -0.73%<br>4.336 → 4.336 GiB pre-write, -0.01%<br>6,236.652 → 7,003.562 rows/s, +12.30% |
| wide-unique write, 1 writer(s) × 64 threads | 2.112 → 1.238 s, -41.37% | 7.263 → 6.750, -7.06% | 27.847 → 28.382 s CPU, +1.92%<br>4.336 → 4.336 GiB pre-write, -0.00%<br>11,837.175 → 20,188.626 rows/s, +70.55% |
| wide-unique-8k write, 8 writer(s) × 8 threads | 9.067 → 6.284 s, -30.69% | 13.922 → 15.030, +7.96% | 50.078 → 50.306 s CPU, +0.45%<br>10.897 → 10.897 GiB pre-write, -0.00%<br>7,058.757 → 10,184.128 rows/s, +44.28% |
| wide-unique-8k write, 8 writer(s) × 64 threads | 1.849 → 1.654 s, -10.55% | 16.832 → 15.770, -6.31% | 76.601 → 78.544 s CPU, +2.54%<br>10.897 → 10.897 GiB pre-write, -0.00%<br>34,616.534 → 38,700.902 rows/s, +11.80% |
| wide-clustered write, 1 writer(s) × 64 threads | 1.879 → 0.060 s, -96.80% | 7.262 → 4.412, -39.24% | 27.765 → 1.803 s CPU, -93.51%<br>4.336 → 4.336 GiB pre-write, -0.00%<br>13,304.203 → 415,283.841 rows/s, +3021.45% |
| wide-mixed write, 1 writer(s) × 64 threads | 2.584 → 1.472 s, -43.04% | 6.911 → 6.467, -6.43% | 27.691 → 28.127 s CPU, +1.57%<br>4.127 → 4.127 GiB pre-write, -0.01%<br>9,676.067 → 16,986.705 rows/s, +75.55% |

Threshold misses (5)

- wide-unique-8k scan RSS
- wide-repeated scan RSS
- wide-repeated take RSS
- wide-clustered scan RSS
- wide-clustered take RSS
