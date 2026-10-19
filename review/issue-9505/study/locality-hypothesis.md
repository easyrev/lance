# V_dense 的选边与 late Take 局部性假设

**状态：仅源码核对，尚无本轮 V_dense 实测计划、地址轨迹或性能结果。** 以下机制允许这个解释，但不能据源码直接认定 DB 已换边、Take 已改善或 DB 比 D 快。审计没有 SSH、构建、测试或冻结源码修改。

## 输入统计的差异成立，但 EOF 不等于 CollectLeft

本节针对 streaming input。V_dense 是 100,000 行 target、90,000 个唯一匹配 source keys，source 只有 id/c0/c1 三个 Int64 列；逻辑值 buffer 为 2,160,000 bytes，约 2.06 MiB，256 行一批，共 352 批。N_dense 是 200,000 行 target、180,000 个唯一 source keys，source 同样三个 Int64，32,768 行一批。两者 source keys 都来自覆盖全 target key 范围的 linspace 后固定 seed permutation；target 按物理行递增生成。因此两者均为 90% 行覆盖率，source encounter order 都打乱。[定义与 source](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/harness/fixtures.py:15)、[共享 key 生成](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/harness/legacy_fixtures.py:73)

B/DB 在普通非索引路径最多尝试原有 100 MiB 和默认 131,072 行预读；只有观察到 EOF 才返回带完整统计的 MemTable。V_dense 在这两个门槛内，可读至 EOF。N_dense 前四批恰好 131,072 行，第五批使 prefix 到 163,840 行即退出，不消费最后一批及 EOF；返回 prefix+tail 的流 provider，不发布完整统计。越界批本身已保留。非 FirstSeen 的 EOF batches 还会按批 round-robin 分配到多个 MemTable partitions，并非一个保序串行 source。[完整预读与门槛](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/B/source/rust/lance/src/dataset/write/merge_insert.rs:2451)

**DF 54.1 的 collect 字节阈值是 1 MiB，与 B 的 100 MiB 缓存上限不同。** `supports_collect_by_thresholds` 在 bytes 可得时只比较 bytes，只有 bytes 不可得才退到 rows；比较使用严格 `<`。因此 V_dense 的完整 source 即使 rows 少于 131,072，也不能凭 rows 取得 CollectLeft 资格：三个必须写回的 Int64 字段本身已超过 1 MiB，join 还可能保留 source sentinel 等字段。[默认阈值](/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-common-54.1.0/src/config.rs:1236)、[collect 判定](/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-physical-optimizer-54.1.0/src/join_selection.rs:121)

在 `target_partitions>1`、默认 `repartition_joins=true` 的普通 HashJoin 计划中，DF 先生成 Auto，再尝试 CollectLeft；两侧都不满足 collect 时使用 Partitioned。两侧都有 bytes 就按 bytes 比较选较小 build，否则尝试 rows；Exact/Inexact 数值都可能使用。只一侧有 collect 资格时也可能直接决定方向，不必两侧大小都可比。因此 V 的 EOF 信息**可能**让 DB 在 Partitioned 模式下换成 source-left/build，但最终是否换边取决于实际投影统计、逻辑/物理优化结果和运行配置；仅 90k/100k 行数不能证明结果。D 的未知流 source 也不能静态保证永远 target build。[规划模式入口](/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-54.1.0/src/physical_planner.rs:1752)、[选边规则](/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-physical-optimizer-54.1.0/src/join_selection.rs:87)、[collect 与 partitioned 分支](/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-physical-optimizer-54.1.0/src/join_selection.rs:224)

如果 cell 使用 materialized input，所有候选都先取得完整 source；D/DB 的“未知流 vs EOF”前提便不成立。当前 harness 明确按 `input_form` 区分，并把外部 materialization 时间单列；B 在 execute 内做的预读仍计入 execute elapsed。[输入及计时入口](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/harness/harness.py:398)

## 换 probe 侧为何可能影响 Take

这些 dense cells 不插入 source-only，也不删除 target-only，因此普通 join 为 Inner。DF HashJoin 左侧 build、右侧 probe；Inner 对右侧输入保持顺序，按当前 probe batch 的匹配 indices 产生结果，再经输出 coalescer。若 D 的 probe 是打乱的 source，映射出的 target rowaddr 会随其打乱顺序；若 DB 的 probe 改为 target scan，则结果可能携带更集中的物理地址片段。source/target keys 在这两个 fixture 中唯一，因此没有重复 key fanout 混淆该对应关系。[probe/order 属性](/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-physical-plan-54.1.0/src/joins/hash_join/exec.rs:933)、[逐 probe batch 匹配](/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-physical-plan-54.1.0/src/joins/hash_join/stream.rs:585)

不过，以下三层会改变这种局部性，不能把“target probe”直接翻译成“全局按 rowaddr 升序”：

1. **target scan 本身未承诺保序。** merge 创建 target provider 时传 `ordered=false`，最终使用 `scan_in_order(false)`。fixture 的存储顺序递增，不等于异步 scan 输出批次必定递增。[DB provider](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/DB/source/rust/lance/src/dataset/write/merge_insert.rs:2695)、[scan 设置](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/src/datafusion/dataframe.rs:230)
2. **Partitioned 要求两侧按 join key hash 分区。** Hash Repartition 在单个输入 batch 内按递增 row index 收集各 bucket，保留该 batch 的子序列；它不会把物理上相邻 key 分配到同一分区。多输入流可以任意交错，每个输出分区还会 coalesce 到 session batch size。RoundRobinBatch 也可能在需要增加并行度的支路出现。是否保留 ordering 取决于实际输入 ordering/partition 属性和优化器，不能从默认开关推出实际节点。[分布要求](/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-physical-plan-54.1.0/src/joins/hash_join/exec.rs:1205)、[batch 内分桶](/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-physical-plan-54.1.0/src/repartition/mod.rs:607)、[交错与 coalesce 合同](/Users/salamanca/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/datafusion-physical-plan-54.1.0/src/repartition/mod.rs:953)
3. **late materializer 再切块，但不排序地址。** condition 节点保持其输入顺序，各分区独立根据观察到的 payload 宽度计算下一片大小，按当前 chunk 中 UpdateAll 的原位置发 Take。join 模式/分区数/上游 batch 大小变化，还会改变软目标和每次 Take 行数，不能只归因于地址顺序。[payload Take](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/D/source/rust/lance/src/dataset/write/merge_insert/exec/condition.rs:453)、[输入顺序属性](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/D/source/rust/lance/src/dataset/write/merge_insert/exec/condition.rs:583)、[分区软目标](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/D/source/rust/lance/src/dataset/write/merge_insert/exec/condition.rs:675)

Take 已经在每次调用内部处理地址局部性：连续地址可直接 read_range；已排序地址按 fragment 分组；未排序地址先排序/去重，按 fragment 读取，再 remap 回请求顺序。因此待证收益应表述为：**换 probe 侧改变每次 Take 包含的地址集合、每次触及的 fragments/pages、跨调用重复读取，以及 sort/remap 工作量。** 它不是“原实现逐行随机 I/O，换边后才批量读”。即使每次内部排序，同一批覆盖整张表与集中在少数相邻页的批次仍可能有不同成本；但缓存、页布局、压缩及解码复用会决定实际差异。[Take 三种路径](/Users/salamanca/workspace/personal/Lance/rust/lance/src/dataset/take.rs:180)、[未排序路径与 remap](/Users/salamanca/workspace/personal/Lance/rust/lance/src/dataset/take.rs:284)

## 实测后最小判别证据

先在**相同 V_dense、streaming、Rows、pool、cache 条件**下拿 D/DB 的实际分析计划，确认左侧来源、Inner join、CollectLeft/Partitioned、各侧 Repartition/Coalesce、输入/输出分区数、target 投影、实际 batch/Take 行数与读取指标。若 DB 没换边，这条“换 probe 侧”解释就不成立；若换边但仍有双侧 hash Repartition，结论应限定为局部批次变化，不能宣称保留全局 scan order。

若时间差值得追查，再在独立 diagnostic 快照记录每个 materializer partition/chunk 的 UpdateAll 地址摘要：行数、unique fragments、每 fragment offset span、是否排序/连续、相邻 chunk 重访的 page/range 或可获得的底层读请求，以及 Take bytes/rows。仅总 payload rows 相同或总读取 bytes 较少不能独自证明地址局部性；总 elapsed 还包含 EOF 预读、hash build、分区复制、Take 解码、gather、完整行写出与 commit。不要在正式计时中加入逐地址日志。

P/DP 固定 source build 且禁用 join repartition/RoundRobin，可提供“target probe + 原 P scan 设置”的另一个观察点；它们同时改变 join 模式、并行和 scan batch policy，所以 DB 对 DP 不是纯局部性消融。B 与 DB 可以观察同类 source 准备/选边下 early vs late，但 DB 还缩窄 target 统计、共享实际 context，也不能预先视作同计划。D 对 DB 包含预读、统计、可能的换边/分区变化，收益未必只是 source 缓存本身。

N_dense 与 V_dense 也不是只跨预读门槛的一对控制实验：行数、target 类型/宽度、fragment 大小及 source batch rows 均不同。可以用它们提出或反驳机制假设，不应把两者性能差异直接归因于 131,072 行门槛。是否补配对或单独地址诊断，待主任务实际结果决定。
