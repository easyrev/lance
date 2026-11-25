# #10526 Linux benchmark criteria

Baseline cb8c25692 and final d0020f429, using the release-with-debug profile in separate target directories and Python environments.

- File size can grow by at most 2% per input.
- Peak process RSS can grow by at most 10% for writes, full scans and random takes.
- Write wall time can grow by at most 10% in every measured combination. Report the 8-writer, 8-thread comparison explicitly.
- Report process CPU time (user plus system during the write interval) alongside wall time.
- Use the median of the three measured repetitions separately for each metric, variant and combination. Exclude warmups. Use the single file-stage write measurement for its peak RSS comparison. Compare full-precision values and retain all trials.
- Before continuing a dataset, require an exact round trip for both builds. Require identical file size and page count for wide-low-card, wide-constant and narrow. For wide-unique, operationalize approximately 3× as compression between 2.5× and 3.5× for both files.
- Report every miss as measured.

Baseline → final. Three measured runs per build and case, summarized by median and min–max. File rows are single observations per build. Max page sizes are logical value payload bytes / sum of encoded page buffers. Per-page encoding details and all trial values are in the raw JSON.

| Case | File or timing | Peak RSS (GiB) | Other |
| --- | --- | --- | --- |
| wide-unique file | 1,534,797,507 B, 1 pages, 4,500,000,000 / 1,534,797,170 B → 1,534,818,518 B, 135 pages, 33,480,000 / 11,420,264 B | 7.263 → 6.713, -7.57%, limit +10% | 1,534,797,507.000 → 1,534,818,518.000, +0.00%, limit +2% B, exact round trips |
| wide-unique scan | 733.701 → 653.904 ms, -10.88%<br>Ranges 686.748–741.564 → 604.890–654.192 | 5.669 → 4.674, -17.55%, limit +10%<br>Ranges 5.401–5.696 → 4.276–4.713 | |
| wide-unique take | 32.444 → 45.427 ms, +40.02%<br>Ranges 31.577–32.676 → 45.362–45.780 | 0.197 → 0.215, +8.80%, limit +10%<br>Ranges 0.197–0.198 → 0.214–0.215 | |
| wide-unique-8k file | 491,127,295 B, 1 pages, 1,440,000,000 / 491,126,941 B → 491,134,489 B, 44 pages, 32,760,000 / 11,175,002 B | 2.472 → 2.518, +1.88%, limit +10% | 491,127,295.000 → 491,134,489.000, +0.00%, limit +2% B, exact round trips |
| wide-unique-8k scan | 373.747 → 366.363 ms, -1.98%<br>Ranges 362.766–389.533 → 354.792–390.805 | 1.999 → 2.516, +25.86%, limit +10%<br>Ranges 1.999–2.001 → 2.393–2.671 | |
| wide-unique-8k take | 32.537 → 45.289 ms, +39.19%<br>Ranges 32.452–33.092 → 44.681–45.724 | 0.198 → 0.215, +8.46%, limit +10%<br>Ranges 0.197–0.199 → 0.214–0.215 | |
| wide-low-card file | 1,483,460 B, 1 pages, 4,500,000,000 / 1,483,113 B → 1,483,460 B, 1 pages, 4,500,000,000 / 1,483,113 B | 4.369 → 4.367, -0.06%, limit +10% | 1,483,460.000 → 1,483,460.000, +0.00%, limit +2% B, exact round trips |
| wide-low-card scan | 92.753 → 93.460 ms, +0.76%<br>Ranges 91.803–123.216 → 91.542–125.907 | 4.279 → 4.381, +2.38%, limit +10%<br>Ranges 4.213–4.379 → 4.184–4.381 | |
| wide-low-card take | 10.107 → 9.977 ms, -1.28%<br>Ranges 9.731–10.529 → 9.966–10.030 | 0.188 → 0.188, -0.01%, limit +10%<br>Ranges 0.187–0.188 → 0.187–0.188 | |
| wide-repeated file | 491,019,071 B, 1 pages, 1,440,000,000 / 491,018,724 B → 20,642,169 B, 44 pages, 32,760,000 / 590,474 B | 2.471 → 1.566, -36.62%, limit +10% | 491,019,071.000 → 20,642,169.000, -95.80%, limit +2% B, exact round trips |
| wide-repeated scan | 366.266 → 121.074 ms, -66.94%<br>Ranges 363.690–371.775 → 120.368–147.116 | 1.999 → 2.390, +19.54%, limit +10%<br>Ranges 1.998–1.999 → 2.276–2.641 | |
| wide-repeated take | 32.093 → 44.901 ms, +39.91%<br>Ranges 32.027–33.042 → 40.595–45.409 | 0.198 → 0.230, +16.30%, limit +10%<br>Ranges 0.196–0.198 → 0.229–0.230 | |
| wide-template file | 1,534,775,171 B, 1 pages, 4,500,000,000 / 1,534,774,865 B → 1,534,796,950 B, 135 pages, 33,480,000 / 11,420,152 B | 7.263 → 6.502, -10.47%, limit +10% | 1,534,775,171.000 → 1,534,796,950.000, +0.00%, limit +2% B, exact round trips |
| wide-template scan | 731.115 → 626.384 ms, -14.32%<br>Ranges 679.297–757.139 → 624.901–643.082 | 5.832 → 4.652, -20.24%, limit +10%<br>Ranges 5.734–5.842 → 4.123–4.803 | |
| wide-template take | 32.589 → 46.352 ms, +42.23%<br>Ranges 32.555–32.863 → 46.181–46.486 | 0.198 → 0.215, +8.85%, limit +10%<br>Ranges 0.197–0.199 → 0.213–0.215 | |
| wide-clustered file | 1,534,448,835 B, 1 pages, 4,500,000,000 / 1,534,448,504 B → 29,506,372 B, 135 pages, 33,480,000 / 296,514 B | 7.261 → 4.413, -39.23%, limit +10% | 1,534,448,835.000 → 29,506,372.000, -98.08%, limit +2% B, exact round trips |
| wide-clustered scan | 827.097 → 241.848 ms, -70.76%<br>Ranges 807.657–840.415 → 238.346–322.801 | 5.604 → 6.241, +11.36%, limit +10%<br>Ranges 5.158–5.756 → 6.225–6.930 | |
| wide-clustered take | 32.148 → 38.885 ms, +20.96%<br>Ranges 32.134–33.092 → 37.921–39.925 | 0.198 → 0.232, +17.50%, limit +10%<br>Ranges 0.194–0.198 → 0.232–0.233 | |
| wide-mixed file | 1,458,139,717 B, 1 pages, 4,275,104,000 / 1,458,139,369 B → 1,458,152,696 B, 128 pages, 33,481,560 / 11,421,839 B | 6.910 → 6.454, -6.61%, limit +10% | 1,458,139,717.000 → 1,458,152,696.000, +0.00%, limit +2% B, exact round trips |
| wide-mixed scan | 783.477 → 638.457 ms, -18.51%<br>Ranges 769.259–795.743 → 626.515–644.068 | 5.393 → 4.446, -17.56%, limit +10%<br>Ranges 5.211–5.432 → 4.363–5.109 | |
| wide-mixed take | 31.611 → 44.150 ms, +39.66%<br>Ranges 31.311–31.845 → 44.059–44.601 | 0.196 → 0.213, +8.57%, limit +10%<br>Ranges 0.195–0.198 → 0.212–0.213 | |
| wide-constant file | 180,251 B, 1 pages, 4,500,000,000 / 180,028 B → 180,251 B, 1 pages, 4,500,000,000 / 180,028 B | 4.364 → 4.365, +0.03%, limit +10% | 180,251.000 → 180,251.000, +0.00%, limit +2% B, exact round trips |
| wide-constant scan | 149.402 → 160.339 ms, +7.32%<br>Ranges 130.186–196.457 → 135.755–160.860 | 4.261 → 4.381, +2.82%, limit +10%<br>Ranges 4.209–4.380 → 4.184–4.381 | |
| wide-constant take | 8.966 → 8.853 ms, -1.27%<br>Ranges 8.762–9.563 → 8.818–8.922 | 0.187 → 0.187, -0.25%, limit +10%<br>Ranges 0.187–0.187 → 0.186–0.187 | |
| narrow file | 28,099,756 B, 1 pages, 80,000,000 / 28,099,448 B → 28,099,756 B, 1 pages, 80,000,000 / 28,099,448 B | 0.293 → 0.293, -0.02%, limit +10% | 28,099,756.000 → 28,099,756.000, +0.00%, limit +2% B, exact round trips |
| narrow scan | 128.743 → 116.960 ms, -9.15%<br>Ranges 124.582–130.352 → 107.811–125.146 | 0.221 → 0.221, -0.08%, limit +10%<br>Ranges 0.221–0.222 → 0.221–0.222 | |
| narrow take | 6.381 → 6.476 ms, +1.49%<br>Ranges 6.377–6.514 → 6.292–6.601 | 0.165 → 0.165, -0.25%, limit +10%<br>Ranges 0.164–0.165 → 0.165–0.165 | |
| wide-unique write, 1 writer(s) × 8 threads | 4.009 → 3.570 s, -10.95%, limit +10%<br>Ranges 3.886–4.049 → 3.032–3.635 | 7.221 → 6.017, -16.68%, limit +10%<br>Ranges 7.221–7.222 → 6.011–6.018 | 19.711 → 19.568 s CPU, -0.73%<br>Ranges 19.542–19.725 → 19.109–19.697<br>4.336 → 4.336 GiB pre-write, -0.01%<br>Ranges 4.336–4.336 → 4.336–4.336<br>6,236.652 → 7,003.562 rows/s, +12.30%<br>Ranges 6,173.704–6,434.110 → 6,877.676–8,246.018 |
| wide-unique write, 1 writer(s) × 64 threads | 2.112 → 1.238 s, -41.37%, limit +10%<br>Ranges 2.033–2.583 → 1.138–1.282 | 7.263 → 6.750, -7.06%, limit +10%<br>Ranges 7.262–7.263 → 6.628–6.757 | 27.847 → 28.382 s CPU, +1.92%<br>Ranges 26.700–28.520 → 28.241–28.890<br>4.336 → 4.336 GiB pre-write, -0.00%<br>Ranges 4.336–4.336 → 4.336–4.336<br>11,837.175 → 20,188.626 rows/s, +70.55%<br>Ranges 9,678.794–12,297.984 → 19,501.384–21,973.307 |
| wide-unique-8k write, 8 writer(s) × 8 threads | 9.067 → 6.284 s, -30.69%, limit +10%<br>Ranges 9.060–9.191 → 6.245–6.293 | 13.922 → 15.030, +7.96%, limit +10%<br>Ranges 13.884–14.018 → 15.004–15.037 | 50.078 → 50.306 s CPU, +0.45%<br>Ranges 49.884–50.566 → 50.269–50.316<br>10.897 → 10.897 GiB pre-write, -0.00%<br>Ranges 10.897–10.897 → 10.897–10.897<br>7,058.757 → 10,184.128 rows/s, +44.28%<br>Ranges 6,963.526–7,063.868 → 10,169.472–10,248.627 |
| wide-unique-8k write, 8 writer(s) × 64 threads | 1.849 → 1.654 s, -10.55%, limit +10%<br>Ranges 1.797–1.909 → 1.632–1.688 | 16.832 → 15.770, -6.31%, limit +10%<br>Ranges 16.450–17.124 → 15.730–15.841 | 76.601 → 78.544 s CPU, +2.54%<br>Ranges 75.877–77.100 → 78.325–79.506<br>10.897 → 10.897 GiB pre-write, -0.00%<br>Ranges 10.897–10.897 → 10.896–10.897<br>34,616.534 → 38,700.902 rows/s, +11.80%<br>Ranges 33,521.888–35,611.114 → 37,922.288–39,209.989 |
| wide-clustered write, 1 writer(s) × 64 threads | 1.879 → 0.060 s, -96.80%, limit +10%<br>Ranges 1.864–1.925 → 0.057–0.069 | 7.262 → 4.412, -39.24%, limit +10%<br>Ranges 7.261–7.262 → 4.412–4.414 | 27.765 → 1.803 s CPU, -93.51%<br>Ranges 27.225–27.943 → 1.717–1.855<br>4.336 → 4.336 GiB pre-write, -0.00%<br>Ranges 4.336–4.336 → 4.336–4.336<br>13,304.203 → 415,283.841 rows/s, +3021.45%<br>Ranges 12,990.196–13,415.085 → 361,334.894–435,807.454 |
| wide-mixed write, 1 writer(s) × 64 threads | 2.584 → 1.472 s, -43.04%, limit +10%<br>Ranges 2.572–2.655 → 1.278–1.749 | 6.911 → 6.467, -6.43%, limit +10%<br>Ranges 6.910–6.911 → 6.460–6.506 | 27.691 → 28.127 s CPU, +1.57%<br>Ranges 26.386–28.122 → 27.921–28.607<br>4.127 → 4.127 GiB pre-write, -0.01%<br>Ranges 4.127–4.127 → 4.127–4.127<br>9,676.067 → 16,986.705 rows/s, +75.55%<br>Ranges 9,416.284–9,720.241 → 14,289.865–19,567.011 |

| Comparisons above the recorded limits | Measured change | Limit |
| --- | ---: | ---: |
| wide-unique-8k scan RSS | +25.86% | +10% |
| wide-repeated scan RSS | +19.54% | +10% |
| wide-repeated take RSS | +16.30% | +10% |
| wide-clustered scan RSS | +11.36% | +10% |
| wide-clustered take RSS | +17.50% | +10% |
