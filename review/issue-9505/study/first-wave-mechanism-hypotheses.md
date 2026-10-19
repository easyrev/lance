# 第一波机制假设与最小诊断指标

本报告只读取本地 `runs/` 的第一波证据及冻结源码，不执行实验。对象是 `survival-main-v1-{F16,Wn,Ws}-{U,B,P,D,CTX,DB,DP}-rewrite_rows-b0`，每格一次；28 个 `correctness-all` 均为 `validated_success`。21 个 survival 格中有 16 个成功、4 个 pool resource failure（CTX 三格、B/Ws）、1 个 cgroup OOM（U/F16）。这些是本次完成状态，不能作为延迟排名或通用稳定性结论。

所有格使用 reader、非索引、Rows、配置的 1 GiB pool、8 GiB cgroup、swap=0；U 的执行 pool 实际行为不能按配置值视作有界。计时位于 `builder.execute(source)` 周围，包含其内部 source 生成/预读、规划与执行，不包含外部构建；见 `harness/harness.py:398–419`。F16 更新 100 行，Wn/Ws 更新 25 行，成功格没有插入或删除。D/DB/DP 的输入 Lance 文件在执行前 mincore 全部驻留；本报告中的 `rchar/wchar` 是进程系统调用字节，不能冒充 Lance scan/Take 指标或冷盘读写。

## 已观察到的差异

下表的 RSS 是 worker 的 `ru_maxrss_bytes`，MiB=2^20 bytes。它含执行前进程历史峰值，不能直接解释成 pool reservation；本组执行前约 157–158 MiB，远低于表中峰值。TMP 是采样到的同时存在文件大小，不能证明累计 spill 为零。原始来源分别为各格的 `metrics.json`、`execute-resources.json` 和 `execute-memory.jsonl`。

| 格 | execute 秒，单次 | CPU 秒 | RSS MiB | TMP 峰值 MiB | rchar bytes | 新数据文件 bytes |
|---|---:|---:|---:|---:|---:|---:|
| F16/D | 0.499 | 2.424 | 1514.1 | 0 | 70,476,965 | 44,782 |
| F16/DB | 0.193 | 0.792 | 284.6 | 0 | 70,476,968 | 44,782 |
| F16/DP | 0.245 | 0.587 | 278.1 | 0 | 70,476,967 | 44,782 |
| Wn/D | 0.235 | 0.410 | 481.1 | 0 | 131,236,135 | 131,079,501 |
| Wn/DB | 0.243 | 0.425 | 495.9 | 0 | 131,231,094 | 131,079,501 |
| Wn/DP | 0.335 | 0.351 | 418.8 | 0 | 131,231,094 | 131,079,501 |
| Ws/D | 1.709 | 1.718 | 1555.2 | 250.001 | 393,400,096 | 393,227,226 |
| Ws/DB | 1.723 | 1.740 | 1560.0 | 250.001 | 393,400,099 | 393,227,226 |
| Ws/DP | 1.220 | 1.287 | 1569.4 | 0 | 131,253,303 | 393,227,226 |

Ws/D、DB 的 `write_bytes` 都是 655,458,304；DP 是 393,310,208。D、DB 的 `wchar` 分别是 655,389,395、655,389,323，DP 是 393,244,346。三者写出的数据文件字节相同，因此这约 250 MiB 的额外读写不能由最终数据文件大小解释。D、DB 的 TMP 峰值准确值都是 262,144,960 bytes，与 source 唯一 batch 的 262,144,400 bytes 接近。**现有记录没有保留活跃临时文件名或算子归属**：内存采样只有大小/数量，退出文件列表只剩 0-byte uv lock。大小接近是线索，不是 spill 归属证据。

B/Ws 的错误明确来自不可 spill 的 `HashJoinInput`：已保留 1000 MiB，申请额外 125 MiB，而 1024 MiB pool 只剩 24 MiB。该格没有 OOM event 增量，不能称为 cgroup OOM。独立 `validate_unchanged.json` 验证版本仍为 1、400 行六列全部保持不变；该次资源失败没有提交部分更新。B/Wn 则成功，但 TMP 峰值 131,075,144 bytes、`rchar=2,228,391,949`，比 P/Wn 多约 125 MiB，值得一并查算子 spill。

## 可验证、可推翻的解释

| 假设 | 源码与本次观测为什么支持继续查 | 最小确认条件 | 什么会推翻或收窄解释 |
|---|---|---|---|
| **H1：B/Ws 在预读越界后仍缺 source 完整统计，实际 hash build 保留宽 target，导致 pool 失败。** | Ws 只有 25 行，但单 batch 约 250 MiB。B 在 batch 越过 100 MiB 后保留该整批并立即停止预读，尚未轮询 EOF，随后采用 one-shot provider；`ports/B/source/rust/lance/src/dataset/write/merge_insert.rs:2484–2516`。错误中的额外申请为 125 MiB，与 target fragment 25×5 MiB 的旧 payload 相容。 | 实际 source provider/统计的 Exact/Inexact/Absent 状态；HashJoin 左右输入 schema、build/probe 来源、mode；失败前 build batches/rows/bytes；申请失败 reservation 名称和 pool 使用量。 | 若实际 build 是 250 MiB source，则“宽 target build”不成立，需要定位保留重复、交换缓冲或 schema 扩宽。若完整 source stats 已存在，则预读推断错误。25 行不能独立证明 source 很小；本格也不能说明“EOF 统计已经获得但仍无效”。 |
| **H2：F16/DB 的 RSS 下降来自较小 build 与不同交换拓扑，而非进一步减少 target 读取。** | D/DB 均 late，`rchar`、输出字节与 TMP 几乎相同；DB 的 100-row/2400-byte source 可以完成 EOF 预读，给 DF 精确 source 统计。D reader 保持未知统计。target key/rowaddr 即使窄，也随 1600 万行增长；DB 若改为保留小 source，可解释 hash 状态下降。 | 两计划的实际 build 来源、`build_input_rows`、`build_mem_used`、`build_time`、各输入 schema 与 Repartition 节点；同一 pool 身份、partition 数和 target scan 投影。 | 若 D/DB 都 build source 且 build bytes 接近，则选边解释不成立；转查 scan 解码并发、channel 缓冲、共享数组保留和 allocator。不能用 RSS 差额直接反推 hash 表大小，也不能把 DB−D 全部收益归到“统计本身”。 |
| **H3：Ws/D、DB 的额外约 250 MiB 临时读写位于携带宽 source 的交换边；DP 避免该边。** | DF 54.1 Repartition 在 channel reservation 不足时把 batch 写入 spill channel。P/DP 禁用 join 重排、join repartition 和 round-robin repartition，source 为逻辑 join 左侧。D/DB 默认优化仍可插入交换。retry=0 排除了 source retry spill；Columns 专用 `update_fragments` 的显式 SortExec 不属于这次 Rows 路径。 | 实际物理树中每个 Repartition/Sort/其他可 spill 算子的输入 schema、位置、partition 数；逐节点逐 partition 的 `spill_count`、`spilled_bytes`、`spilled_rows`，确认约 250 MiB 对应哪个节点；其上下游输入 rows/bytes。 | 若 Repartition spill 为零而 Sort/其他节点有对应 spill，就归因到后者；若实际树无该交换边，当前假设不成立。若 spill 输入是 join 输出/target，也不能称为“source spill”。零 TMP 采样本身不能证明零 spill。DP 的 RSS 及 cgroup 峰值并未同步下降，不能把少临时 I/O 等同于更低总内存。 |
| **H4：Wn/DP 的首轮额外 wall time 可能来自较小 scan batch 或较低流水并行；当前也允许只是噪声。** | D/DB/DP 都无采样 TMP，读取和最终写入量接近；DP 的 CPU 时间反而较少。P/DP 按全文件平均行宽估 batch，Wn 的旧 payload 为 5 MiB/row，即使 DP 只 scan key/rowaddr 也沿用此估算；`ports/DP/source/rust/lance/src/dataset/write/merge_insert.rs:1232–1236,1263–1280`。 | 目标 scan 的实际 batch rows 分布、批次数、并发 decode 数、I/O buffer；join/condition 输出 partition 数；payload Take 调用数、候选行/批；CPU 与关键路径等待时间。随后用预定交叉重复核验差异是否保留。 | 若 scan batch/并行与 D/DB 相同，宽度估计解释不成立；若 wall 差异在重复中消失，不再寻找必然源码原因。若 Take 调用/读请求明显增加，解释应改为批间随机访问成本，不能只说“P 关闭并行”。 |

H3 的候选路径有明确实现依据：本地 DF 54.1 `datafusion-physical-plan/src/repartition/mod.rs:180–190` 在 `try_grow` 失败后调用 `spill_writer.push_batch`，`:1221–1234` 把 SpillMetrics 挂在该 Repartition 节点上。需要读取这些节点指标再归属。P/DP 配置依据为 `ports/DP/source/rust/lance/src/dataset/write/merge_insert.rs:1237–1242`，source-left join 为 `:2830–2831`。这些源码条件不代替实际优化后的树。

## 正式 diagnose 最少需要保留什么

1. **真实输入产生的物理树及统计。** 沿用同一 fixture、reader batch、写模式、pool、重试和候选身份，记录 HashJoin mode（CollectLeft/Partitioned）、左右来源和全部字段、每条 Repartition 的类型/partition 数、scan 投影及是否存在 Sort。记录 source 预读是否读到 EOF、provider 类型和双方 rows/bytes 的统计精度。schema-only explain 不能代表 B 的 EOF 路径；producer.jsonl 记录“yield 了一批”，不证明 consumer 已轮询 EOF。
2. **Hash build/probe。** DF 54.1 已有 `build_input_batches`、`build_input_rows`、`build_mem_used`、`build_time`、probe 的 `input_batches`/`input_rows`、`join_time`、`output_rows`。这些定义见本地 `datafusion-physical-plan/src/joins/utils.rs:1476–1545`。保留逐 partition 值及树结构，区分共享 CollectLeft build，避免把 gauge 简单求和冒充 RSS。失败时尽可能保留截至失败的指标及 reservation 错误；失败不返回 analyzed-plan 时，不能把缺失报告当成零。
3. **交换与 spill。** 每个节点的 `spill_count`、`spilled_bytes`、`spilled_rows` 是 H3 的首要区分指标；Repartition 的 `fetch_time`、`repartition_time`、`send_time` 辅助定位等待与搬运。先看节点归属，再用 TMP 峰值和进程 rchar/wchar/write_bytes 对账；spill bytes 是累计口径，TMP 是同时存活口径，二者无需严格相等。若指标仍不够，再取带算子标签的活跃临时文件记录，不能仅靠文件大小命名原因。
4. **scan 与 late Take 分开。** scan 记录投影、output rows/batches/bytes、`bytes_read`/`iops`/`requests`、实际 batch rows、decode 并发和配置 I/O buffer；这些 I/O 指标的名称见 `rust/lance-datafusion/src/utils.rs:240–242`。D 节点已有 `condition_take_rows`、`condition_take_arrow_bytes`、`payload_take_rows`、`payload_take_arrow_bytes`、`payload_reused_condition_values`，见 `ports/D/source/rust/lance/src/dataset/write/merge_insert/exec/condition.rs:635–644`。本轮无条件，预期 condition counters 为零，payload rows 分别为 100/25/25。**Arrow bytes 不是存储读取字节**；该节点直接调用 TakeBuilder（`:399–406,482–489`），不能假定物理树里的独立 TakeExec I/O 指标自动覆盖这些内部读取。现有 counters 没有 Take 调用数、地址分布和每次请求字节；只有现有指标不能区分时，才值得在独立诊断版本加这些观测。
5. **对齐关键路径和证据边界。** 保留 execute 的 wall/CPU、执行前 RSS、worker HWM、cgroup anon/file/peak、输出文件字节和 oracle；analyze 另存为诊断，不混入计时样本。Wn 的额外约 0.1 秒需要重复才能确认；Ws 的额外临时读写已经是观测事实，但归属与其时间占比仍待查。完整 28 格 correctness 通过、三场景资源完成状态，以及本次单轮时间差，是三个不同结论。

对 F16 首先诊断 D↔DB 的 build 状态；对 Ws 首先诊断 D/DB↔DP 的 spill 节点；对 Wn 首先比较 scan 批次和流水并发，再结合交叉重复。B/Ws 必须保留失败计划证据，才能判断 B 的预读边界是否是这次失效的直接原因。这些检查只选择下一步解释，不据此宣布 DB、DP 或默认 deferred payload 胜出。
