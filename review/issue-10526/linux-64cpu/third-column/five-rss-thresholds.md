| 数据集 | 操作 | 上轮 base → final | 本轮 base → final | 本轮 base → final+B |
|---|---|---:|---:|---:|
| wide-unique-8k | scan | +25.86% | +21.15% (超标) | -1.43% (达标) |
| wide-repeated | scan | +19.54% | +9.97% (达标) | +26.19% (超标) |
| wide-repeated | take | +16.30% | +16.66% (超标) | +19.80% (超标) |
| wide-clustered | scan | +11.36% | +14.37% (超标) | +20.95% (超标) |
| wide-clustered | take | +17.50% | +17.49% (超标) | +20.45% (超标) |

原门槛口径为每组 3 进程的中位数。加跑后的 5 进程结果如下，完整区间见 [三列结果](summary.md)。

| 数据集 | 操作 | base → final | base → final+pure-B |
|---|---|---:|---:|
| wide-repeated | scan | +9.53%（达标） | +19.34%（超标） |
| wide-clustered | scan | +14.68%（超标） | +16.32%（超标） |
