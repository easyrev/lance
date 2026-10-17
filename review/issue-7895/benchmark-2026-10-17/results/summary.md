# PR #9617 scaling benchmark summary

## 结论摘要

本轮完成了 288 次隔离子进程运行：287 次成功且结果校验通过，另有 1 次是 D 层预期的 upstream `ENOSPC`。两边各 144 条记录；upstream 固定为 `dc53d5d174af62c49ddd98d1024a64488c1e4404`，PR 为相同补丁 rebase 后的 `e18df5f4708b42be99aa33ec9ac12de15401982f`。测量期间没有修改 PR 代码，也没有 push 或在 GitHub 留言。

核心结论如下：

- PR 对本轮已测的合格文件源，在 DataFusion 四档热缓存、4 GiB 冷缓存和 1 GiB legacy indexed 路径中都把 replay 临时文件消除为 0 B。
- upstream 的 spill 确实随源大小近似线性增长，但 H1 的预登记公式不成立。100 MiB 是切换到磁盘的阈值，不是永久保留在内存的前缀；超过阈值后，之前缓存的 batch 也被写入 Arrow IPC，实测文件约为逻辑 Arrow 源大小的 1.031 倍。
- PR 无冲突路径与自身 `conflict_retries=0` 对照非常接近：merge wall 偏差为 -2.07% 到 +2.39%，进程 CPU 偏差为 -1.88% 到 +0.92%。源大小不小于 1 GiB 时，没有触发“PR 无冲突中位延迟比 upstream 慢 5% 以上”的分析阈值。
- 重试内存结果取决于源实现。LanceDataset 冲突组的直接 PR-vs-upstream RSS 对比没有正向回退；Parquet 的冲突组 PR 相对 upstream 多用 39 MiB、492 MiB、2,983 MiB、5,068 MiB，随规模增长。
- Parquet 重试必须再次读取和解码，这是可重扫方案的固有工作；数 GiB RSS 放大并非该语义必然要求。诊断证据指向 PyArrow 按 batch 数预取宽行数据，allocator 对比结果与 mimalloc 保留已释放页面一致。降低 readahead 明显收窄 CPU、Arrow pool 和 RSS，但 readahead 与 allocator 的单因子检查各只有 1 次，只覆盖 1 GiB 本地热缓存，还不能直接作为最终修复。

## 指标与实验口径

- `wall` 使用 `merge_wall_s`，只覆盖 `builder.execute(source)`。
- `CPU` 和 `peak RSS` 来自父进程对整个新子进程的 `wait4`；CPU 包含 Python import、source 构造和结果采集，因此通常比 merge-window CPU 高约 2 秒。
- `spill` 的主指标是每轮独立 `TMPDIR` 的直接观测峰值，不包含目标数据集的正常写入。`/proc/<pid>/io` 的写入差值只作交叉验证。
- `source size` 是 Arrow 逻辑字节数，不是 Parquet 文件大小或实际物理读取量。
- 小于等于 4 GiB 的主热缓存单元各 5 次；16 GiB 各 3 次；4 GiB 冷缓存各 3 次；P 层各 3 次；D 层各 1 次。
- 每次运行前恢复到固定 tag，热缓存预读目标和源，冷缓存执行 `sync` 后 drop page cache。runner 固定按 upstream、PR 交替执行。
- 每个成功样本检查预期行数、版本增量，并抽样核对 81 行的 `id`、`vec`、`label`、`ts` 全部列。

## 开跑前核实

1. Python `merge_insert(...)` 默认 `conflict_retries=10`。upstream 的普通 reader 路径先进入 `stream_source_to_provider`；重试开启时由 `spilling_table_provider(..., 100 * 1024 * 1024)` 建立 replay buffer。
2. replay 文件由 `tempfile::tempdir()` 创建，服从 `std::env::temp_dir()` / `TMPDIR`。每轮独立 TMPDIR 中都能直接看到 `spill.arrows`；D 层也以真实 `ENOSPC` 验证了该路径。
3. replay provider 在 DataFusion/legacy 执行路径分叉前建立。P 层的 1 GiB indexed legacy 路径中，upstream TMP 峰值为 1,055.652 MiB，PR 为 0 B，确认两条路径都受益。
4. 冲突 hook 在第一次提交前插入一次竞争提交。104 个成功冲突样本均为 2 次 commit attempt、版本增加 2；183 个成功无冲突样本均为 1 次 attempt、版本增加 1。
5. retry 使用 `SlotBackoff`，随机数来自 OS RNG，第一轮耗时还是 backoff 单位。现有参数不能关闭或固定它，因此冲突 wall 只作参考；CPU、RSS、spill 是主要判断指标。

## 构建与测试

- upstream 与 rebased PR 均用 `release-with-debug`，分别构建到独立 target directory 并安装到独立 venv。
- `lance-datafusion`：233 passed。
- Rust `merge_insert` 定向测试：334 passed，5,844 filtered out。
- PyO3 replayable 单元测试：4 passed。
- `python/tests/test_dataset.py`：348 passed，5 skipped，3 warnings，21.36 秒。

## H1–H6 判定

### H1：不成立，但线性增长结论成立

| Tier | Source size, MiB | `max(source - 100 MiB, 0)`, MiB | Upstream TMP peak, MiB | TMP/source |
|---|---:|---:|---:|---:|
| 128 MiB | 127.999 | 27.999 | 131.957 | 1.03092 |
| 1 GiB | 1,023.999 | 923.999 | 1,055.652 | 1.03091 |
| 4 GiB | 4,095.999 | 3,995.999 | 4,222.598 | 1.03091 |
| 16 GiB | 16,384.000 | 16,284.000 | 16,890.395 | 1.03091 |

阈值被跨过后，spilling provider 会把先前的内存 batch 和后续 batch 一并序列化到 Arrow IPC；IPC 元数据等开销使落盘量约为逻辑 Arrow 大小的 1.031 倍。因此不能用“源大小减 100 MiB”估计临时盘容量。

### H2：在本轮测量范围内成立

PR 的 A 层 84 次 eligible-source 运行、P 层 3 次 legacy-path 运行以及 D 层成功样本，直接 TMP 峰值全部为 0 B。范围限定为本轮测到的 Lance/Parquet 文件源和这些规模；不能据此外推所有第三方 `pa.dataset.Dataset` 实现。

### H3：成立

PR 默认路径相对自身 A0 对照的偏差如下：

| Tier | Source | Wall delta | CPU delta |
|---|---|---:|---:|
| 128 MiB | Lance | +2.39% | -0.43% |
| 128 MiB | Parquet | -2.07% | -0.58% |
| 1 GiB | Lance | -0.47% | -1.58% |
| 1 GiB | Parquet | +0.50% | +0.66% |
| 4 GiB | Lance | -1.89% | -1.88% |
| 4 GiB | Parquet | -1.20% | -1.37% |
| 16 GiB | Lance | -0.02% | -0.73% |
| 16 GiB | Parquet | -0.34% | +0.92% |

A0 是经验对照，不是数学下界；测量噪声会让默认路径偶尔略快。upstream 相对 A0 的绝对回放开销随规模扩大：Lance 的 wall 从 +0.201 秒增至 +4.109 秒、CPU 从 +0.345 秒增至 +33.003 秒；Parquet 的 wall 从 +0.161 秒增至 +4.039 秒、CPU 从 +0.245 秒增至 +34.968 秒。

### H4：取决于源实现；Parquet 回退随规模增长

| Tier | Parquet conflict CPU PR−U, s | Parquet conflict RSS PR−U, MiB | Retry-specific CPU gap, s | Retry-specific RSS gap, MiB |
|---|---:|---:|---:|---:|
| 128 MiB | -0.061 | +38.6 | +0.319 | +47.4 |
| 1 GiB | +2.637 | +492.3 | +4.579 | +372.1 |
| 4 GiB | +9.625 | +2,983.2 | +18.250 | +2,037.1 |
| 16 GiB | +35.141 | +5,068.0 | +68.891 | +4,478.9 |

这里的 retry-specific gap 是 `(conflict - no-conflict)_PR - (conflict - no-conflict)_upstream`。它能帮助隔离趋势，但峰值 RSS 不能严格相减归因，因此 RSS 差中差只是启发式量。LanceDataset 的冲突 CPU 和 RSS 直接对比在四档都低于 upstream，说明去掉 replay spill 的净收益覆盖了重扫成本，不能据此推断 Lance 重扫没有额外工作。Lance 的 retry-specific CPU gap 仍从 +0.252 秒增至 +14.300 秒；数 GiB 且随规模扩大的正向 RSS 差值集中在 Parquet scanner 路径。

### H5：回退契约成立；“所有字节字段逐字相同”不成立

B 层 40 次均验证通过。两个版本的 replay-buffer 路径、merge stats、冲突次数和 commit attempts 一致；20 组 upstream/PR 配对的直接 TMP 峰值逐字节相同：Arrow Scanner 为 1,106,919,424 B，RecordBatchReader 为 1,106,931,712 B。

| Source | Conflict | Wall med U → PR, s | CPU U → PR, s | RSS U → PR, MiB | TMP U → PR, MiB |
|---|---:|---:|---:|---:|---:|
| Arrow Scanner | 0 | 3.410 → 3.369 | 14.946 → 15.151 | 6,003 → 6,048 | 1,055.641 → 1,055.641 |
| Arrow Scanner | 1 | 10.113 → 13.798 | 20.220 → 20.417 | 6,592 → 6,442 | 1,055.641 → 1,055.641 |
| RecordBatchReader | 0 | 3.024 → 3.019 | 10.243 → 10.342 | 3,658 → 3,666 | 1,055.652 → 1,055.652 |
| RecordBatchReader | 1 | 9.046 → 9.259 | 14.765 → 14.732 | 4,782 → 4,298 | 1,055.652 → 1,055.652 |

派生的 `wchar` spill 估计最多相差 731 B，派生 write spill 最多相差 4,620 B，目标写入最多相差 34,759 B。因此不能写成“all metrics were identical”。这些微小差异没有显示资格判断或 fallback 分叉，未触发 H5 的 hard stop。Arrow Scanner 冲突 wall 的中位数差异较大，但没有对应的 CPU 差异，而且 wall 指标受随机 backoff 影响。

### H6：成立

| Build | 2 GiB ext4-loop TMPDIR result | Merge wall | CPU | Peak RSS | Observed TMP peak |
|---|---|---:|---:|---:|---:|
| upstream | Failed: `No space left on device (os error 28)` | n/a | 16.672 s | 4,988 MiB | 1,929.820 MiB |
| PR | Success; result verified | 8.747 s | 23.243 s | 6,621 MiB | 0 B |

每边只有一次运行；这是功能边界验证，不是性能分布。

## 路径确认与冷缓存

P 层 1 GiB Lance、BTREE indexed legacy path：upstream → PR 的 wall 为 6.721 → 5.534 秒，CPU 为 19.943 → 18.106 秒，RSS 为 4,482 → 3,583 MiB，TMP 为 1,055.652 MiB → 0 B。PR 在 legacy path 同样消除了 replay spill。

4 GiB 冷缓存结果如下；冲突 wall 同样受随机 backoff 影响：

| Source | Conflict | Wall median (p90) U → PR, s | CPU U → PR, s | RSS U → PR, MiB | TMP U → PR, MiB |
|---|---:|---:|---:|---:|---:|
| Lance | 0 | 9.570 (9.580) → 8.514 (8.637) | 32.002 → 23.628 | 6,974 → 7,060 | 4,222.598 → 0 |
| Lance | 1 | 39.088 (48.888) → 47.036 (47.338) | 46.883 → 42.030 | 8,675 → 7,595 | 4,222.602 → 0 |
| Parquet | 0 | 10.850 (10.868) → 9.271 (9.508) | 44.257 → 37.451 | 7,821 → 8,702 | 4,222.562 → 0 |
| Parquet | 1 | 54.614 (55.067) → 50.644 (50.858) | 62.473 → 74.028 | 7,652 → 11,709 | 4,222.566 → 0 |

## Parquet 重试回退的根因分析

### 可确认的代码与运行时事实

- PR 为 `pa.dataset.FileSystemDataset` 保留 replayable factory。每个 retry attempt 都重新扫描 provider；retry loop 串行执行。没有发现两个 attempt 的 reader 并发存活或 retry reader 未释放的代码/运行时证据。
- upstream 冲突重放已解码并写入 Arrow IPC 的数据；PR 冲突时必须第二次读 Parquet 并解码 definition/repetition levels。这部分 CPU 工作是可重扫设计的固有取舍。
- 1 GiB Parquet 的 flat `perf cpu-clock` 样本中，libparquet 归因约从 1.70 CPU 秒增至 3.82 CPU 秒，增加约 2.12 秒，约占这对 profile 的 `cpu-clock` 差值的 79%。共同热点包括 `DefRepLevelsToListInfo`、`GreaterThanBitmapAvx2`、`TypedRecordReader::DelimitRecords` 和 `LevelDecoder::Decode`。
- brief 要求的 1 GiB LanceDataset perf/heaptrack profiles 已完成。有效 perf profile 的 `cpu-clock` 为 upstream 13.545 秒、PR 12.566 秒；热点结构相近，主要是 Arrow `take_native`、libc/缺页和 encoding statistics，没有出现 PR 独有的集中热点。Heaptrack 自身摘要中的 upstream/PR peak live heap 为 1.69/1.92 GB，包含 profiler 开销的 peak RSS 为 4.80/4.81 GB，总 leaked memory 为 8.56/9.23 MB；没有出现 Parquet 相同的 RSS 分离形态。主矩阵随后把正向 RSS 回退定位到 Parquet，因此又对 Parquet 跑了相同 profiles。
- 1 GiB Parquet heaptrack profile 的 upstream/PR peak live heap 为 1.34/1.43 GB，包含 profiler 开销的 peak RSS 为 4.74/7.23 GB，总 leaked memory 为 8.61/9.20 MB。约 0.09 GB 的 live-heap 增量解释不了主矩阵中数 GiB 的 RSS 差值；这次 profile 没有观察到足以解释该差值的 live-heap leak 证据。Heaptrack 明显扰动运行时和 RSS，这些数只用于分配形态，不进入主表。

### Harness-only 定向诊断

以下都使用 PR、1 GiB Parquet、一次强制冲突，且结果校验通过；这些是诊断运行，不属于主矩阵，也没有修改 PR：

| Scanner/allocator mode | n | Process CPU median | Peak RSS median | Arrow pool max median | RSS at first commit median |
|---|---:|---:|---:|---:|---:|
| Current reused scanner, default readahead, mimalloc | 3 | 21.218 s | 7,312 MiB | 3,096.5 MiB | 5,419.6 MiB |
| Current reused scanner, system allocator | 1 | 20.937 s | 4,516.6 MiB | 3,153.5 MiB | 2,302.8 MiB |
| Reused scanner, readahead=1 only | 1 | 16.988 s | 5,639.9 MiB | 1,868.3 MiB | 4,273.0 MiB |
| Reused scanner, batch_size=16,384 only | 1 | 20.625 s | 7,018.3 MiB | 3,114.5 MiB | 5,399.7 MiB |
| Fresh bounded scanner, batch_size=16,384 and readahead=1 | 3 | 15.144 s | 3,179.0 MiB | 349.8 MiB | 1,692.2 MiB |

默认宽表扫描的 Arrow pool 峰值约 3.1 GiB；进入 commit 时 live pool bytes 已回到 0，但 mimalloc 下 RSS 仍约 5.4–5.6 GiB。换 system allocator 时 pool 峰值基本不变，第一次 commit 的 RSS 降到 2.30 GiB；这组单次对比与 allocator page retention 一致，但不足以称为 mimalloc bug。单独减小 batch size 没有改善；把 readahead 降到 1 明显降低 pool、CPU 和 RSS；两者同时限制后 pool 峰值降到约 350 MiB。

综合判断：第二次 Parquet 解码是固有成本；当前 RSS 和部分 CPU 放大是可优化实现细节，主要来自按 batch 数预取约 3.1 KiB/row 的宽表，随后 allocator 保留已释放页面。优先优化方向是按“在途字节数”限流，或根据估算行宽自适应降低 replayable scanner 的 readahead。单独降低 batch size 不足以解决问题。`readahead=1` 在本地热缓存诊断中没有显示首轮 wall 回退，但还需要冷缓存、远程对象存储和受影响矩阵验证。本轮按要求没有直接修改 PR；若要实现该方向，应先确认方案，再单独提交并重跑。

## 数据可信度与未测内容

- p90 使用 nearest-rank；n=5 或 n=3 时就是该组最大值，不是稳定的尾延迟估计。
- runner 固定 upstream → PR，而非 ABBA 或随机顺序。ABAB 配对减轻了长期漂移，但仍可能有位置偏差。
- 冲突 backoff 使用 OS 随机源，且以第一轮耗时为单位；冲突 wall 只能作参考。
- Parquet 的 `source_read_bytes` 没有采集；Arrow 逻辑字节数不能代替实际物理读取量。
- `perf` 没有硬件 cycles/instructions，只能用 `cpu-clock` 和较平的符号归因，适合判断热点方向，不适合微架构结论。
- Heaptrack 严重扰动运行，不能把其 wall/RSS 与主矩阵直接比较。
- RSS 差中差是启发式指标，不能解释成精确的 retry 内存分配量。
- TMPDIR 每 50 ms 采样一次，因此报告的是 observed peak。upstream spill 文件在执行期间长期存在，H1/D 对这一采样间隔不敏感。
- C 远程源未测：实例没有 RAM role，也没有现成 RustFS/MinIO 和 toxiproxy；没有使用长期密钥，也没有临时拼装一个不可比的远程栈。本地 NVMe 热缓存结果不能外推为对象存储结论。
- profiler 和 scanner/allocator 诊断脚本只存在于 benchmark harness，没有提交到 PR。

## Performance section for the PR

### Performance

We benchmarked public PR head `ff576648` after rebasing the same patch onto upstream `dc53d5d`; the local rebased commit was `e18df5f`, and both PR commits had the same stable patch ID. The host was an Alibaba Cloud `ecs.i4r.4xlarge` instance with 16 vCPU, 128 GiB RAM, and local NVMe. The target contained 4 million rows, and each source row was about 3.1 KiB wide. Each successful run verified the final row count, version count, and 81 sampled rows across all columns.

Wall time measures the `merge_insert` call. CPU time and peak RSS cover the full child process and come from `wait4`. All CPU-time and peak-RSS values below are group medians. Replay spill is the observed peak size in the per-run `TMPDIR`; it excludes target-dataset writes. Source size is the logical Arrow size. Values are upstream / PR. Default uses `conflict_retries=10`; A0 uses `conflict_retries=0` for the same build. Every A0 direct TMP peak was 0 B. Main cells used five samples through 4 GiB and three samples at 16 GiB.

#### No conflict

| Source | Size | Rows | Replay spill U → PR | Default wall median (p90), s | Default CPU median, s | Default peak RSS median, MiB | A0 wall median (p90), s | A0 CPU median, s | A0 peak RSS median, MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Lance | 128 MiB | 42,963 | 132 MiB → 0 | 0.75 (0.77) / 0.64 (0.64) | 3.6 / 3.3 | 1,212 / 837 | 0.55 (0.56) / 0.62 (0.65) | 3.3 / 3.3 | 950 / 832 |
| Parquet | 128 MiB | 42,963 | 132 MiB → 0 | 0.81 (0.82) / 0.73 (0.76) | 4.0 / 3.6 | 1,474 / 1,465 | 0.65 (0.66) / 0.75 (0.76) | 3.7 / 3.6 | 1,463 / 1,472 |
| Lance | 1 GiB | 343,707 | 1,056 MiB → 0 | 2.95 (2.99) / 2.66 (2.82) | 10.2 / 8.1 | 3,568 / 3,411 | 2.57 (2.74) / 2.67 (2.76) | 8.1 / 8.2 | 3,506 / 3,501 |
| Parquet | 1 GiB | 343,707 | 1,056 MiB → 0 | 3.31 (3.44) / 2.88 (3.19) | 15.0 / 13.0 | 6,149 / 6,270 | 2.77 (2.81) / 2.87 (2.94) | 12.6 / 12.9 | 6,070 / 6,156 |
| Lance | 4 GiB | 1,374,829 | 4,223 MiB → 0 | 9.66 (9.83) / 8.61 (8.71) | 31.3 / 22.7 | 7,177 / 7,000 | 8.59 (8.70) / 8.78 (8.86) | 23.2 / 23.2 | 7,059 / 6,981 |
| Parquet | 4 GiB | 1,374,829 | 4,223 MiB → 0 | 10.58 (10.96) / 9.21 (9.28) | 47.8 / 39.2 | 8,702 / 9,648 | 9.30 (9.54) / 9.32 (9.57) | 39.7 / 39.7 | 9,858 / 9,561 |
| Lance | 16 GiB | 5,499,318 | 16,890 MiB → 0 | 34.32 (35.10) / 30.49 (31.59) | 103.9 / 71.4 | 11,050 / 9,494 | 30.21 (30.63) / 30.50 (30.71) | 70.9 / 72.0 | 9,534 / 9,495 |
| Parquet | 16 GiB | 5,499,318 | 16,890 MiB → 0 | 37.37 (37.40) / 32.93 (33.12) | 175.5 / 141.8 | 12,745 / 13,334 | 33.33 (33.76) / 33.04 (33.17) | 140.5 / 140.5 | 13,354 / 13,291 |

For the PR, no-conflict wall and CPU medians stayed within 2.4% of its retries-disabled control. Upstream's absolute replay overhead grew with the source: about 0.2 to 4.1 seconds of wall time and 0.2 to 35.0 seconds of process CPU across the tested sizes. No source at or above 1 GiB triggered the preregistered “PR is more than 5% slower” condition.

Once the 100 MiB threshold was crossed, upstream wrote the buffered prefix and all later batches to Arrow IPC. Its replay file therefore tracked the full source size, at about 1.031x the logical Arrow bytes, instead of `source size - 100 MiB`.

#### One forced conflict

| Source | Size | Rows | Replay spill U → PR | Wall median (p90), s | CPU median, s | Peak RSS median, MiB |
|---|---:|---:|---:|---:|---:|---:|
| Lance | 128 MiB | 42,963 | 132 MiB → 0 | 2.97 (3.84) / 2.83 (3.49) | 4.6 / 4.5 | 1,709 / 1,405 |
| Parquet | 128 MiB | 42,963 | 132 MiB → 0 | 1.51 (4.20) / 2.39 (4.17) | 5.1 / 5.0 | 1,805 / 1,843 |
| Lance | 1 GiB | 343,707 | 1,056 MiB → 0 | 12.78 (15.46) / 8.35 (11.65) | 14.6 / 13.5 | 4,537 / 4,243 |
| Parquet | 1 GiB | 343,707 | 1,056 MiB → 0 | 13.54 (17.53) / 12.51 (16.19) | 20.3 / 22.9 | 6,718 / 7,210 |
| Lance | 4 GiB | 1,374,829 | 4,223 MiB → 0 | 39.28 (50.98) / 27.29 (49.22) | 46.5 / 42.3 | 8,496 / 8,052 |
| Parquet | 4 GiB | 1,374,829 | 4,223 MiB → 0 | 43.13 (44.08) / 29.46 (40.67) | 66.7 / 76.3 | 8,806 / 11,790 |
| Lance | 16 GiB | 5,499,318 | 16,890 MiB → 0 | 178.49 (179.00) / 135.27 (135.50) | 159.2 / 141.0 | 12,899 / 11,054 |
| Parquet | 16 GiB | 5,499,318 | 16,890 MiB → 0 | 108.76 (110.91) / 105.77 (186.09) | 242.6 / 277.7 | 12,757 / 17,826 |

Conflict wall time includes randomized retry backoff and is shown only for completeness. CPU time, peak RSS, and replay spill are the primary conflict metrics. Every successful conflict run had exactly two commit attempts.

The retry RSS result was source-dependent. Lance sources did not show a positive direct PR regression, although their retry-specific CPU delta still grew with source size because rescanning repeats source work. Parquet sources did show a positive RSS regression: the direct conflict gap grew from 39 MiB at 128 MiB to 5,068 MiB at 16 GiB. The second Parquet decode is an inherent cost of rescanning after a conflict; upstream replays already decoded Arrow IPC. The measured RSS amplification does not appear inherent. One-run factor checks point to batch-count-based scanner readahead on wide rows, and the allocator comparison is consistent with page retention after those buffers are released. Lower readahead reduced Arrow-pool use, CPU, and process RSS, but this still needs cold-cache and remote-source validation before changing the PR.

#### Restricted temporary disk

| Build | 4 GiB Lance source with 2 GiB ext4-loop TMPDIR |
|---|---|
| upstream | Failed with `ENOSPC` after the observed TMP peak reached 1,929.8 MiB |
| PR | Succeeded, verified the result, and used 0 B of TMPDIR |

#### Additional controls and unmeasured cases

- A 1 GiB legacy indexed-path check reduced replay spill from 1,055.7 MiB to 0 B, confirming that the PR avoids spill on both the DataFusion and legacy paths.
- Opaque Arrow Scanner and RecordBatchReader controls retained the fallback path in both builds. Their paired direct TMP peaks, retry counts, and merge statistics matched.
- The 4 GiB cold-cache matrix reproduced zero PR replay spill and the source-dependent Parquet retry RSS pattern.
- Remote object storage was not measured. The instance had no RAM role and no ready RustFS/MinIO with toxiproxy setup, and no long-lived credentials were used.
- Physical Parquet source-read bytes were not collected.
- Hardware cycles and instructions were unavailable; `perf` used `cpu-clock` with flat symbol attribution.
- p90 uses nearest rank. With three or five samples it is the maximum observation, not a stable tail-latency estimate.
