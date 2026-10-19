# 本轮原始记录摘要

这是 26 格诊断结束、正式配对开始前的提取快照。末尾 comparison 的 incomplete 仅表示当时尚未运行配对；最终完整 53 格和三轮比率见 results.md / results.json。

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

## 同 block 配对

| group | numerator / denominator | rounds | median ratio |
|---|---|---:|---:|
| pairs-h2-ws | parallel-small/p | 0/3 | incomplete |
| pairs-h2-rr | split/small | 0/3 | incomplete |
| pairs-h3-wn | generic/condition | 0/3 | incomplete |
| pairs-h3-n | generic/early | 0/3 | incomplete |
| pairs-h3-n | condition/early | 0/3 | incomplete |
| pairs-h3-n | generic/condition | 0/3 | incomplete |
