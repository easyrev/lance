# PR 1 候选取舍

最终选择 pure-B，提交 `16e3c99b1faa6014c17e33331f35cce726302243`。交接单要求 pure-B-var 在无压缩或混合页上有收益，且相对 pure-B 在其他数据集上没有回归。

| 数据集和指标 | pure-B | pure-B-var | pure-B → pure-B-var | 每构建进程数 |
|---|---:|---:|---:|---:|
| binary-medium-default scan 时间，ms | 921.93 [883.03–933.57] | 912.67 [899.95–1026.39] | -1.00% | 5 |
| binary-medium-default scan 峰值 RSS，MiB | 1933.35 [1918.96–2183.62] | 2058.36 [1886.96–2238.33] | +6.47% | 5 |
| binary-medium-default take(1024) 第 6–20 次，ms | 6.91 [6.77–7.42] | 6.94 [6.81–7.31] | +0.44% | 5 |
| mixed take(1024) 首次，ms | 84.62 [83.62–84.64] | 62.37 [61.90–63.05] | -26.29% | 3 |
| mixed take(1024) 进程峰值 RSS，MiB | 371.61 [369.35–377.64] | 328.03 [326.63–331.36] | -11.73% | 3 |
| binary-zstd-medium scan 峰值 RSS，MiB | 2061.11 [2001.37–2291.31] | 2385.82 [2294.76–2708.38] | +15.75% | 3 |

pure-B-var 相对 pure-B 在 `binary-zstd-medium` 的 scan 峰值 RSS、`utf8-1page` 的 take(1024) 第二次时间和首次峰值 RSS、`utf8-1page` 的 take(128) 进程峰值 RSS，以及 `utf8-zstd-25k` 的 take(1024) 第二次时间中，中位数增加且两组区间不重叠。完整的各方向回归和 N=3、N=5 结果见 [回归汇总](phase1-regressions.md) 和 [阶段 1 表](phase1.md)。

在 `utf8-zstd-25k` 上，pure-B 对 main 的 scan 时间和峰值 RSS 分别下降 12.02% 和 15.26%（各 5 进程），take(128) 首次调用时间和进程峰值 RSS 分别下降 31.07% 和 13.53%（各 3 进程）。在 `binary-zstd-varlen` 上，scan 时间和峰值 RSS 分别下降 10.14% 和 22.71%，take(128) 首次时间下降 34.24%（各 3 进程）。
