# 本轮原始记录摘要

完整配置、实际算子/分区指标及 scope 见对应 spec/metrics/plan；下表不构成跨计时范围排名。

| case | status | seconds | CPU s | reservation peak MiB | RSS MiB | TMP MiB |
|---|---|---:|---:|---:|---:|---:|
| h1-complete-current | execution_error | 0.026365 | 0.190 | 48.00 | 313.66 | 0.00 |
| h1-complete-guard | success | 0.569940 | 0.990 | 9.01 | 668.19 | 32.00 |
| h1-complete-manifest | execution_error | 0.031204 | 0.220 | 48.00 | 316.96 | 0.00 |
| h1-original-reverse-guard-plan | plan_only | — | — | 0.00 | 52.20 | 0.00 |
| h1-reader-current | execution_error | 0.027960 | 0.210 | 48.00 | 323.83 | 0.00 |
| h1-reader-guard | success | 0.536937 | 0.890 | 9.01 | 649.44 | 32.00 |
| h1-reader-manifest | execution_error | 0.026942 | 0.190 | 48.00 | 319.80 | 0.00 |
| h1-reader-mask-only-plan | plan_only | — | — | 0.00 | 54.58 | 0.00 |
| h1-reverse-complete-guard | success | 0.004162 | 0.010 | 0.25 | 110.74 | 0.00 |
| h1-reverse-reader-guard | success | 0.004450 | 0.010 | 0.37 | 109.75 | 0.00 |
| h2-merge-Ws-p | success | 2.374073 | 4.400 | 250.00 | 2685.66 | 0.00 |
| h2-merge-Ws-parallel | success | 7.980710 | 10.550 | 250.01 | 5012.54 | 755.01 |
| h2-merge-Ws-parallel-small | success | 2.978135 | 5.400 | 490.02 | 2767.49 | 430.05 |
| h2-merge-Ws_multi-p | success | 2.439407 | 4.390 | 250.01 | 2851.91 | 0.00 |
| h2-merge-Ws_multi-parallel | success | 7.508151 | 10.080 | 250.76 | 4965.31 | 750.01 |
| h2-merge-Ws_multi-parallel-small | success | 2.820959 | 5.280 | 490.02 | 3199.00 | 430.05 |
| h2-rr-Ws-batch1-split0 | success | 1.063926 | 0.880 | 0.00 | 562.90 | 250.00 |
| h2-rr-Ws-batch1-split16777216 | success | 0.293042 | 0.380 | 100.00 | 460.17 | 0.00 |
| h2-rr-Ws-batch8192-split0 | success | 1.087800 | 0.870 | 0.00 | 564.08 | 250.00 |
| h2-rr-Ws_multi-batch1-split0 | success | 0.143371 | 0.250 | 180.01 | 193.36 | 0.00 |
| h2-rr-Ws_multi-batch8192-split0 | success | 0.306408 | 0.390 | 200.63 | 350.32 | 0.00 |
| h3-N_dense-condition | success | 0.244248 | 0.330 | 13.43 | 215.92 | 0.00 |
| h3-N_dense-early | success | 0.037011 | 0.050 | 21.76 | 135.89 | 0.00 |
| h3-N_dense-generic | success | 0.083220 | 0.450 | 13.16 | 262.90 | 0.00 |
| h3-Wn-condition | success | 0.167074 | 0.180 | 0.20 | 196.27 | 0.00 |
| h3-Wn-generic | success | 0.389341 | 0.470 | 0.20 | 538.24 | 0.00 |
| pairs-h2-rr-b1-small | success | 1.049579 | 0.850 | 0.00 | 563.78 | 250.00 |
| pairs-h2-rr-b1-split | success | 0.297578 | 0.390 | 100.00 | 453.28 | 0.00 |
| pairs-h2-rr-b2-small | success | 1.137602 | 0.850 | 0.00 | 563.69 | 250.00 |
| pairs-h2-rr-b2-split | success | 0.295100 | 0.390 | 100.00 | 454.53 | 0.00 |
| pairs-h2-rr-b3-small | success | 1.077316 | 0.860 | 0.00 | 563.70 | 250.00 |
| pairs-h2-rr-b3-split | success | 0.297245 | 0.390 | 110.00 | 458.77 | 0.00 |
| pairs-h2-ws-b1-p | success | 2.439625 | 4.500 | 250.00 | 2973.98 | 0.00 |
| pairs-h2-ws-b1-parallel-small | success | 3.144754 | 5.580 | 490.02 | 2705.32 | 430.05 |
| pairs-h2-ws-b2-p | success | 2.347953 | 4.390 | 250.00 | 2743.38 | 0.00 |
| pairs-h2-ws-b2-parallel-small | success | 3.141522 | 5.490 | 490.02 | 2994.20 | 430.05 |
| pairs-h2-ws-b3-p | success | 2.378396 | 4.410 | 250.00 | 2848.74 | 0.00 |
| pairs-h2-ws-b3-parallel-small | success | 3.221617 | 5.670 | 490.02 | 2778.15 | 430.05 |
| pairs-h3-n-b1-condition | success | 0.242177 | 0.320 | 13.24 | 211.03 | 0.00 |
| pairs-h3-n-b1-early | success | 0.036813 | 0.050 | 22.03 | 132.34 | 0.00 |
| pairs-h3-n-b1-generic | success | 0.071470 | 0.460 | 13.09 | 256.12 | 0.00 |
| pairs-h3-n-b2-condition | success | 0.240290 | 0.330 | 13.51 | 226.03 | 0.00 |
| pairs-h3-n-b2-early | success | 0.036672 | 0.050 | 21.50 | 136.04 | 0.00 |
| pairs-h3-n-b2-generic | success | 0.083164 | 0.450 | 13.16 | 258.33 | 0.00 |
| pairs-h3-n-b3-condition | success | 0.236427 | 0.330 | 13.51 | 207.43 | 0.00 |
| pairs-h3-n-b3-early | success | 0.036835 | 0.050 | 22.03 | 134.69 | 0.00 |
| pairs-h3-n-b3-generic | success | 0.071469 | 0.450 | 13.09 | 259.13 | 0.00 |
| pairs-h3-wn-b1-condition | success | 0.162408 | 0.170 | 0.20 | 181.11 | 0.00 |
| pairs-h3-wn-b1-generic | success | 0.369712 | 0.450 | 0.20 | 595.86 | 0.00 |
| pairs-h3-wn-b2-condition | success | 0.161044 | 0.170 | 0.20 | 187.31 | 0.00 |
| pairs-h3-wn-b2-generic | success | 0.376103 | 0.460 | 0.20 | 607.01 | 0.00 |
| pairs-h3-wn-b3-condition | success | 0.165197 | 0.180 | 0.20 | 186.81 | 0.00 |
| pairs-h3-wn-b3-generic | success | 0.363169 | 0.450 | 0.20 | 542.88 | 0.00 |

## 同 block 配对

| group | numerator / denominator | rounds | median ratio |
|---|---|---:|---:|
| pairs-h2-ws | parallel-small/p | 3/3 | 1.337984 |
| pairs-h2-rr | split/small | 3/3 | 0.275912 |
| pairs-h3-wn | generic/condition | 3/3 | 2.276445 |
| pairs-h3-n | generic/early | 3/3 | 1.941430 |
| pairs-h3-n | condition/early | 3/3 | 6.552415 |
| pairs-h3-n | generic/condition | 3/3 | 0.302287 |
