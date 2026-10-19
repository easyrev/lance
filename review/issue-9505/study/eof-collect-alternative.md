# 完整小 source 的 collect 备选

状态：**仅源码预研，未实现、未构建、未测量，不新增候选。** 对象是 U `0a0d327` 上冻结 DB 与 DataFusion 54.1。主任务报告的首轮为 N_dense：CTX 0.066 s / RSS 294 MiB，D 0.109 s / 406 MiB；V_dense：CTX 0.843 s / 1043 MiB，D 0.914 s / 621 MiB。V_dense 约慢 8%，同时减少内存；这些单轮数据不能确认需要新策略。先完成现有 B/P/DB/DP 的 N/V 对照和三轮配对。

## 适用性首先限制了它的价值

`harness/fixtures.py:15–22` 中 N_dense 有 180000 行 source，超过 B 的 131072 行预读停止界限；即使前缀已经接近全部输入，也没有观察到 EOF，DB 仍走 fallback。**只对完整小 EOF source 生效的规则不会改善这次 N_dense 回退。** 不应为命中该 fixture 调大预读阈值。

V_dense 有 90000 行、三个 Int64 source 字段，原始数组约 2.06 MiB，能在 B 现有限额内观察 EOF。DF 的 collect byte 阈值默认 1 MiB；有 byte statistics 时直接比较 bytes，不再用 rows < 131072 兜底。因此“B 已完整缓存”不等于“DF 已采用 CollectLeft”。这使 V_dense 成为有区分力的现有格，但是否实际为 source-build Partitioned，必须看该候选最终计划。

## 如果证据支持，首个变体只改一种已选计划

建议保留 DB 原选边，只把“**完整小 EOF source 已经被 DF 选为 build 的 Partitioned join**”改为 CollectLeft。未知/prefix、target-build、已有 CollectLeft 都不变。这样保留小 target / 大未知 source 的反向出口，也避免改变 F16 等已经 collect 的小 source 格。首轮范围可限 eligible partial-schema Rows、UpdateAll、无 inserts/target-only deletes；不扩写模式或外围路由。

最小接口是让 source 准备返回 provider 加完整性证据，例如 `Complete { rows, arrow_bytes }` 或 `PrefixOrUnknown`，传到同一 attempt 的规划入口。EOF 证据只描述 source，不携带 target 地址；retry 必须重新进行 target scan、选边和计划构造。不得从带 sentinel 的 ProjectionExec 的推导统计反推 EOF，也不得把 prefix 统计伪装成 Exact。显式 materialized/provider 入口首轮可保持现状，避免顺手扩大范围。

计划变换应在 DF `JoinSelection` 之后、`EnforceDistribution` 之前，仅匹配本次 merge 的 join。用现有 `HashJoinExec` builder 改 `PartitionMode`，保留已选左右输入、join type、filter、projection 和 NULL 规则。这样不需再次 swap 字段。不能在最终计划上直接删 Hash Repartition：子节点分区合同可能已不满足新 join。需要显式插入 optimizer rule 的位置；直接追加规则到整个 optimizer 列表末尾不够。

对应源码：`ports/DB/source/rust/lance/src/dataset/write/merge_insert.rs:2463–2518,2673–2690,2906–2912`；DF `join_selection.rs:118–143,315–342`、`optimizer.rs:162–177`；HashJoin `exec.rs:1066–1099,1205–1223`。这是一个候选机制的最小设计，不是已完成的可应用补丁。

## Collect 与单路 probe 的区别

CollectLeft 的 build 由 `OnceAsync` 在 probe partitions 间共享，只建立一次；并不把完整 hash table 复制 P 份（DF HashJoin `exec.rs:733–737,1341–1360`）。它要求左侧 SinglePartition，右侧只要求 UnspecifiedDistribution，所以仍可能加入 RoundRobin。去掉按 key 的 Hash Repartition 有机会保留 target batch 内的地址局部性，但不保证整个输出按 row address 排序；target scanner 本身仍是 unordered，多个 probe partition 仍可交错。

P 式单路 probe 是进一步的变化。全 session 关闭 `repartition_joins` 会预先选择 CollectLeft，关闭 RoundRobin 会减少 probe 并行；若再关闭 join_reordering，就会丢掉 DB 的反向选边能力。因此不建议把 P 的三个开关一起复制过来。首个备选只验证 collect/shared-build；只有实际计划和局部性证据表明 RoundRobin 仍主导代价，才考虑单路 probe 及其独立成本。

## 反例、归因和维护成本

- EOF 只证明完整，不证明 hash build 能放入实际 pool。B 的 100 MiB 阈值不是 HashJoin 内存上界，缓存、拼接、hash map 和输出还会同时驻留。collect 规则不能据此成为无条件安全默认；也不能用资源错误后任意重放来掩盖回退，因为 writer 可能已经开始工作。
- 如果 DF 选择 target build，source 是随机顺序 probe，仅移除 Hash Repartition 仍会得到分散的 target 地址；此备选明确不强迫 source build。允许 target 继续作 build 是保留反向容量出口的代价。
- Collect 还可能改变动态过滤、并行调度和整数 key 的 ArrayMap 使用。DF HashJoin `exec.rs:538–568` 明确说明 Partitioned 可把密集整数 key 拆成稀疏集合。因此速度变化不能全部归因于 Take 局部性；应同时检查最终 build 侧、分区方式、scan/join/action 计数及 hash 指标。Arrow Take 返回字节不是物理读取字节或峰值内存。
- source 完整性证据需贯穿 reader/analyze/retry，局部 optimizer rule 需维护顺序与 source provenance。它比调整一个全局 threshold 多，但不新增统计伪装、文件格式或写回机制。现有 FirstSeen、NULL、outer actions 和 retry 测试仍需在实际变体上验证，不能把冻结 DB 的通过结果直接转移过去。

## 与排序备选及最小验证的关系

全局 row-address sort 能处理 N_dense 这类 source 未完整缓存的输入，并直接聚集 mutation 地址，但需要完整 action/source 值屏障、排序/可能 spill，还可能与 hash join 争同一 pool。collect 只利用已完整 source 和现有 hash join，额外结构较小，覆盖也更窄。二者都不能仅因机制可测就进入候选；排序边界仍见 `sort-alternative-notes.md`。

若后续证据确实要求验证，现有 harness 只需先用 **V_dense** 检查 DB 与该备选的完整值、最终计划、时间/RSS和局部性，再用 **R_admission** 检查未知 source 的反向出口未改变。N_dense 的 eligibility 应在计划级测试中明确保持 fallback，不新增同规模性能格。若 V_dense 的 DB 已经 CollectLeft，或现有 DP/P 及三轮结果不支持 hash 重分区相关代价，就不启动这个备选。
