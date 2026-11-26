# Bridging 快路径对照

逐行对应旧版 `ed4c87940` 的 base → pure 比较，共 96 项。

| 旧判定 | 本轮判定 | 项数 |
|---|---|---|
| 在噪声内 | 在噪声内 | 40 |
| 在噪声内 | 收益 | 4 |
| 收益 | 在噪声内 | 4 |
| 收益 | 收益 | 48 |

## 旧收益未保留（4 项）

| 数据集 | 操作 | 指标 | 旧变化 | 旧判定 | 本轮变化 | 本轮判定 |
|---|---|---|---|---|---|---|
| utf8-zstd-25k | scan | 耗时 ms | -13.10% | 收益 | -4.44% | 在噪声内 |
| utf8-zstd-8k | scan | 峰值 RSS MiB | -21.11% | 收益 | -11.27% | 在噪声内 |
| binary-zstd-varlen | scan | 峰值 RSS MiB | -20.80% | 收益 | -12.06% | 在噪声内 |
| binary-zstd-medium | repeat1024 | 进程峰值 RSS MiB | -5.49% | 收益 | -6.81% | 在噪声内 |

## 旧表在噪声内且本轮超出噪声（4 项）

| 数据集 | 操作 | 指标 | 旧变化 | 旧判定 | 本轮变化 | 本轮判定 |
|---|---|---|---|---|---|---|
| utf8-1page | repeat128 | 第 6–20 次 ms | +0.13% | 在噪声内 | -1.35% | 收益 |
| utf8-zstd-8k | scan | 耗时 ms | -10.25% | 在噪声内 | -8.76% | 收益 |
| binary-random-varlen | scan | 耗时 ms | -5.16% | 在噪声内 | -5.92% | 收益 |
| binary-random-varlen | scan | 峰值 RSS MiB | -10.23% | 在噪声内 | -8.54% | 收益 |

## 对照组超出噪声（1 项）

| 数据集 | 操作 | 指标 | 旧变化 | 旧判定 | 本轮变化 | 本轮判定 |
|---|---|---|---|---|---|---|
| utf8-1page | repeat128 | 第 6–20 次 ms | +0.13% | 在噪声内 | -1.35% | 收益 |

## 全部判定（96 项）

| 数据集 | 操作 | 指标 | 旧变化 | 旧判定 | 本轮变化 | 本轮判定 |
|---|---|---|---|---|---|---|
| utf8-1page | scan | 耗时 ms | -0.63% | 在噪声内 | -0.77% | 在噪声内 |
| utf8-1page | scan | 峰值 RSS MiB | +0.89% | 在噪声内 | +0.91% | 在噪声内 |
| utf8-1page | repeat128 | 首次 ms | -0.08% | 在噪声内 | -0.16% | 在噪声内 |
| utf8-1page | repeat128 | 第二次 ms | -2.13% | 在噪声内 | -1.71% | 在噪声内 |
| utf8-1page | repeat128 | 第 6–20 次 ms | +0.13% | 在噪声内 | -1.35% | 收益 |
| utf8-1page | repeat128 | 首次峰值 RSS MiB | +0.04% | 在噪声内 | +0.78% | 在噪声内 |
| utf8-1page | repeat128 | 进程峰值 RSS MiB | +0.32% | 在噪声内 | +0.14% | 在噪声内 |
| utf8-1page | repeat1024 | 首次 ms | +0.25% | 在噪声内 | -1.05% | 在噪声内 |
| utf8-1page | repeat1024 | 第二次 ms | +0.72% | 在噪声内 | -1.10% | 在噪声内 |
| utf8-1page | repeat1024 | 第 6–20 次 ms | +0.54% | 在噪声内 | -0.85% | 在噪声内 |
| utf8-1page | repeat1024 | 首次峰值 RSS MiB | -0.77% | 在噪声内 | -0.07% | 在噪声内 |
| utf8-1page | repeat1024 | 进程峰值 RSS MiB | -0.20% | 在噪声内 | +0.26% | 在噪声内 |
| utf8-zstd-25k | scan | 耗时 ms | -13.10% | 收益 | -4.44% | 在噪声内 |
| utf8-zstd-25k | scan | 峰值 RSS MiB | -14.70% | 在噪声内 | -16.34% | 在噪声内 |
| utf8-zstd-25k | repeat128 | 首次 ms | -28.11% | 收益 | -28.93% | 收益 |
| utf8-zstd-25k | repeat128 | 第二次 ms | -31.41% | 收益 | -30.98% | 收益 |
| utf8-zstd-25k | repeat128 | 第 6–20 次 ms | -5.63% | 收益 | -6.82% | 收益 |
| utf8-zstd-25k | repeat128 | 首次峰值 RSS MiB | -8.06% | 收益 | -6.98% | 收益 |
| utf8-zstd-25k | repeat128 | 进程峰值 RSS MiB | -7.53% | 收益 | -7.61% | 收益 |
| utf8-zstd-25k | repeat1024 | 首次 ms | -26.21% | 收益 | -26.67% | 收益 |
| utf8-zstd-25k | repeat1024 | 第二次 ms | -24.11% | 收益 | -24.36% | 收益 |
| utf8-zstd-25k | repeat1024 | 第 6–20 次 ms | -24.33% | 收益 | -24.80% | 收益 |
| utf8-zstd-25k | repeat1024 | 首次峰值 RSS MiB | -26.42% | 收益 | -26.84% | 收益 |
| utf8-zstd-25k | repeat1024 | 进程峰值 RSS MiB | -26.04% | 收益 | -26.61% | 收益 |
| utf8-zstd-8k | scan | 耗时 ms | -10.25% | 在噪声内 | -8.76% | 收益 |
| utf8-zstd-8k | scan | 峰值 RSS MiB | -21.11% | 收益 | -11.27% | 在噪声内 |
| utf8-zstd-8k | repeat128 | 首次 ms | -27.51% | 收益 | -27.57% | 收益 |
| utf8-zstd-8k | repeat128 | 第二次 ms | -24.31% | 收益 | -29.21% | 收益 |
| utf8-zstd-8k | repeat128 | 第 6–20 次 ms | -5.50% | 收益 | -7.29% | 收益 |
| utf8-zstd-8k | repeat128 | 首次峰值 RSS MiB | -8.36% | 收益 | -8.38% | 收益 |
| utf8-zstd-8k | repeat128 | 进程峰值 RSS MiB | -7.58% | 收益 | -7.42% | 收益 |
| utf8-zstd-8k | repeat1024 | 首次 ms | -28.05% | 收益 | -27.71% | 收益 |
| utf8-zstd-8k | repeat1024 | 第二次 ms | -14.25% | 收益 | -15.66% | 收益 |
| utf8-zstd-8k | repeat1024 | 第 6–20 次 ms | -15.61% | 收益 | -16.37% | 收益 |
| utf8-zstd-8k | repeat1024 | 首次峰值 RSS MiB | -35.46% | 收益 | -34.96% | 收益 |
| utf8-zstd-8k | repeat1024 | 进程峰值 RSS MiB | -27.78% | 收益 | -27.54% | 收益 |
| binary-zstd-varlen | scan | 耗时 ms | -8.53% | 收益 | -9.91% | 收益 |
| binary-zstd-varlen | scan | 峰值 RSS MiB | -20.80% | 收益 | -12.06% | 在噪声内 |
| binary-zstd-varlen | repeat128 | 首次 ms | -29.19% | 收益 | -29.36% | 收益 |
| binary-zstd-varlen | repeat128 | 第二次 ms | -32.81% | 收益 | -32.48% | 收益 |
| binary-zstd-varlen | repeat128 | 第 6–20 次 ms | -32.69% | 收益 | -32.01% | 收益 |
| binary-zstd-varlen | repeat128 | 首次峰值 RSS MiB | -10.82% | 收益 | -10.81% | 收益 |
| binary-zstd-varlen | repeat128 | 进程峰值 RSS MiB | -10.49% | 收益 | -10.27% | 收益 |
| binary-zstd-varlen | repeat1024 | 首次 ms | -24.85% | 收益 | -24.45% | 收益 |
| binary-zstd-varlen | repeat1024 | 第二次 ms | -19.63% | 收益 | -19.11% | 收益 |
| binary-zstd-varlen | repeat1024 | 第 6–20 次 ms | -20.65% | 收益 | -19.95% | 收益 |
| binary-zstd-varlen | repeat1024 | 首次峰值 RSS MiB | -37.90% | 收益 | -38.14% | 收益 |
| binary-zstd-varlen | repeat1024 | 进程峰值 RSS MiB | -27.94% | 收益 | -28.05% | 收益 |
| binary-random-varlen | scan | 耗时 ms | -5.16% | 在噪声内 | -5.92% | 收益 |
| binary-random-varlen | scan | 峰值 RSS MiB | -10.23% | 在噪声内 | -8.54% | 收益 |
| binary-random-varlen | repeat128 | 首次 ms | -32.25% | 收益 | -33.12% | 收益 |
| binary-random-varlen | repeat128 | 第二次 ms | -26.83% | 收益 | -28.18% | 收益 |
| binary-random-varlen | repeat128 | 第 6–20 次 ms | -25.81% | 收益 | -25.07% | 收益 |
| binary-random-varlen | repeat128 | 首次峰值 RSS MiB | -7.05% | 收益 | -6.80% | 收益 |
| binary-random-varlen | repeat128 | 进程峰值 RSS MiB | -8.52% | 收益 | -12.36% | 收益 |
| binary-random-varlen | repeat1024 | 首次 ms | -30.35% | 收益 | -29.46% | 收益 |
| binary-random-varlen | repeat1024 | 第二次 ms | -15.32% | 收益 | -14.13% | 收益 |
| binary-random-varlen | repeat1024 | 第 6–20 次 ms | -17.66% | 收益 | -14.65% | 收益 |
| binary-random-varlen | repeat1024 | 首次峰值 RSS MiB | -22.04% | 收益 | -23.63% | 收益 |
| binary-random-varlen | repeat1024 | 进程峰值 RSS MiB | -26.81% | 收益 | -28.20% | 收益 |
| binary-zstd-medium | scan | 耗时 ms | +0.04% | 在噪声内 | -1.13% | 在噪声内 |
| binary-zstd-medium | scan | 峰值 RSS MiB | -14.53% | 在噪声内 | -11.01% | 在噪声内 |
| binary-zstd-medium | repeat128 | 首次 ms | -1.72% | 在噪声内 | -1.95% | 在噪声内 |
| binary-zstd-medium | repeat128 | 第二次 ms | -4.03% | 在噪声内 | -4.72% | 在噪声内 |
| binary-zstd-medium | repeat128 | 第 6–20 次 ms | -5.62% | 收益 | -4.44% | 收益 |
| binary-zstd-medium | repeat128 | 首次峰值 RSS MiB | -0.29% | 在噪声内 | +0.04% | 在噪声内 |
| binary-zstd-medium | repeat128 | 进程峰值 RSS MiB | -0.28% | 在噪声内 | +0.11% | 在噪声内 |
| binary-zstd-medium | repeat1024 | 首次 ms | -18.40% | 收益 | -17.30% | 收益 |
| binary-zstd-medium | repeat1024 | 第二次 ms | -21.81% | 收益 | -22.00% | 收益 |
| binary-zstd-medium | repeat1024 | 第 6–20 次 ms | -4.89% | 收益 | -4.93% | 收益 |
| binary-zstd-medium | repeat1024 | 首次峰值 RSS MiB | -4.87% | 收益 | -5.22% | 收益 |
| binary-zstd-medium | repeat1024 | 进程峰值 RSS MiB | -5.49% | 收益 | -6.81% | 在噪声内 |
| binary-medium-default | scan | 耗时 ms | +0.55% | 在噪声内 | +2.12% | 在噪声内 |
| binary-medium-default | scan | 峰值 RSS MiB | +6.23% | 在噪声内 | +5.27% | 在噪声内 |
| binary-medium-default | repeat128 | 首次 ms | +1.00% | 在噪声内 | -1.21% | 在噪声内 |
| binary-medium-default | repeat128 | 第二次 ms | +3.05% | 在噪声内 | -0.92% | 在噪声内 |
| binary-medium-default | repeat128 | 第 6–20 次 ms | +0.85% | 在噪声内 | +2.11% | 在噪声内 |
| binary-medium-default | repeat128 | 首次峰值 RSS MiB | -0.20% | 在噪声内 | +0.40% | 在噪声内 |
| binary-medium-default | repeat128 | 进程峰值 RSS MiB | +0.01% | 在噪声内 | +0.42% | 在噪声内 |
| binary-medium-default | repeat1024 | 首次 ms | -1.21% | 在噪声内 | -0.17% | 在噪声内 |
| binary-medium-default | repeat1024 | 第二次 ms | +1.90% | 在噪声内 | -0.12% | 在噪声内 |
| binary-medium-default | repeat1024 | 第 6–20 次 ms | +0.85% | 在噪声内 | +2.46% | 在噪声内 |
| binary-medium-default | repeat1024 | 首次峰值 RSS MiB | +0.06% | 在噪声内 | -0.81% | 在噪声内 |
| binary-medium-default | repeat1024 | 进程峰值 RSS MiB | -0.52% | 在噪声内 | -0.10% | 在噪声内 |
| mixed | scan | 耗时 ms | -9.43% | 收益 | -7.12% | 收益 |
| mixed | scan | 峰值 RSS MiB | -25.51% | 收益 | -19.69% | 收益 |
| mixed | repeat128 | 首次 ms | +0.47% | 在噪声内 | +1.02% | 在噪声内 |
| mixed | repeat128 | 第二次 ms | +0.02% | 在噪声内 | +1.21% | 在噪声内 |
| mixed | repeat128 | 第 6–20 次 ms | +0.38% | 在噪声内 | +1.06% | 在噪声内 |
| mixed | repeat128 | 首次峰值 RSS MiB | -0.15% | 在噪声内 | +0.67% | 在噪声内 |
| mixed | repeat128 | 进程峰值 RSS MiB | +0.50% | 在噪声内 | +0.32% | 在噪声内 |
| mixed | repeat1024 | 首次 ms | -0.49% | 在噪声内 | +0.40% | 在噪声内 |
| mixed | repeat1024 | 第二次 ms | +0.62% | 在噪声内 | -1.28% | 在噪声内 |
| mixed | repeat1024 | 第 6–20 次 ms | -0.35% | 在噪声内 | -2.76% | 在噪声内 |
| mixed | repeat1024 | 首次峰值 RSS MiB | +0.06% | 在噪声内 | -0.02% | 在噪声内 |
| mixed | repeat1024 | 进程峰值 RSS MiB | +0.87% | 在噪声内 | +0.17% | 在噪声内 |

## 本地诊断

使用固定 head 的独立工作树加临时日志。下表为 composite task 次数。扫描运行一次，take 用同一句柄运行 20 次。详细日志和临时补丁见 [raw/diagnostic](raw/diagnostic)。

| 数据集 | 操作 | 多页 bridging 成功 | 多页 concat | 单页 concat | bridging 错误 |
|---|---|---:|---:|---:|---:|
| utf8-zstd-25k | scan | 25 | 0 | 0 | 0 |
| utf8-zstd-8k | scan | 8 | 0 | 0 | 0 |
| binary-zstd-varlen | scan | 12 | 0 | 0 | 0 |
| binary-zstd-medium | repeat1024 | 20 | 0 | 0 | 0 |
| utf8-1page | repeat128 | 0 | 0 | 20 | 0 |

四项旧收益未保留的对应诊断用例均观察到多页 bridging 成功，排除这些用例整体静默回退。
对照组 `utf8-1page` 的 `repeat128` 观察到 0 次多页 bridging 成功。

### 返回 None 的位置

位置为原始 `d4cac03` 下的源代码行。同一 fallback 可同时计入页级与 composite 上层检查。

| 数据集 | 操作 | 位置和检查 | 次数 |
|---|---|---|---:|
| utf8-1page | repeat128 | `field.rs:934 single-page` | 20 |
