# Lance #9505 / #10077 统一候选 C：可实现设计与验证决策

日期：2026-10-18  
状态：设计 v0.1；尚未实现、构建或运行本候选的 benchmark。  
配套任务书：codex-ecs-validation.md。

## 0. 目标与本轮交付

本方案同时以 Candidate B 和 #10077 为对照，争取一个综合更有竞争力的非索引 merge 实现：小 source、大 target 的主场景足够快；大 source、小 target 时仍有合理选边；宽字段不会仅因行数少被误判为小 build；扫描并行不会无意放大原有资源窗口。

这是一个统一 proposal。Ccore 和 Clate 是同一设计中的可单独测量部分，实施与消融顺序不代表必须先提交统计 PR。是否拆分提交，在验证出值得保留的机制后决定。

本稿已经决定首轮如何处理未知输入、统计可信度、分区数、扫描资源、延迟补列及回退。它没有证明 C 已经胜过 B 或 #10077；ECS 工作负责验证这些判断，并淘汰收益不足的部分。所有新增类型名、实验开关和伪码均为拟议接口。

### 冻结对照

| 对象 | revision |
| --- | --- |
| U：调查基线 main | dc53d5d174af62c49ddd98d1024a64488c1e4404 |
| B：已有小流统计候选 | 793e4e27119540a17ae37ce78d4f5f4d52060a93 |
| P：#10077 与基线合并后的测试版 | f8859373d5022eedea239db2fcfd68713a423762 |
| #10077 原始 head | 9e1ebc2e816a7195b56757ebe269e74989fc30c7 |
| 调查材料快照 | 3fd5356239b91c0d38e818b0c7237e9545d1db11 |
| 配套 DataFusion | 54.1.0 |

这些 revision 是可复核的历史基线，不能称为以后执行时的最新 main。先在相同基线上比较，再决定是否移植到更新的 upstream。原始 [README][S1]、[REPORT][S2] 已明确：B 与 P 的组合没有被测试过。

## 1. 从已有证据确定要解决的三个成本

### 1.1 构建侧需要留住多少状态

HashJoin 先保留一侧输入并建立哈希表，再逐批匹配另一侧。build 的大小包括投影后的 Arrow 数据、哈希索引、拼接时的并存数组、键表达式和某些 join 所需的 visited bitmap，不能只用行数或 source 预读字节代表。[DF hash build][S5]

B 通过小 source 的完整统计改善选边，保留优化器；P 固定 source build，并联动改变 pool、扫描预算和并行配置。已有 reverse 结果说明固定 source build 有代价：100K target / 3M full-schema source、1 GiB DF pool 的旧测试中 B 成功，P 出现 pool error。相反，旧 64M × 44 列、reader 100 场景中 P 约 3.007 s，B 约 5.957 s。两者配置有多项差异，不能把速度差全部归因于 RoundRobin。[REPORT][S2]

### 1.2 数据通过多少队列，多少批在同时推进

现有普通 Lance 扫描可以内部并行、对外只输出一路；DF 随后可能添加 RoundRobin 来提供多路 probe。Lance 已有 MultiplePartitions 模式，DF 也有 repartitioned 接口，允许扫描器直接提供输出分区。[扫描实现][S6]、[DF 分布优化][S7]

接通这个接口有机会减少中间调度和缓冲，同时保留 probe 并行。但旧队列也能隔离上下游速度，原生模式还有共享任务流的锁，因此减少一个算子不等于一定更快。

### 1.3 匹配前是否读取了大量最终不需要的旧字段

RewriteRows 在 source 缺少字段时，需要保留旧字段来写出完整新行。当前路径会让这些字段提前进入 target scan / join。对极少数实际更新行，可以在决定 action 后才按地址取旧字段；这会同时缩小扫描投影、join 数据和早期驻留。[merge logical plan][S10]、[writer][S12]

source 很小无法证明实际更新很少：目标重复键可能让 100 个 source key 匹配数百万行。还要区分“更新行比例”和“读取所覆盖的存储页比例”。因此本轮给延迟补列一个完整实施契约和强制对照模式，不提前发明自动选择阈值。

## 2. 统一结构与明确边界

Ccore 包含四项：有界 source 准备、merge 局部统计保护与初始选边、统一资源设置、合格 target scan 的原生分区。

Clate 在同一结构中增加 RewriteRows 缺失旧字段的延迟读取。它通过更窄的实际投影反过来改善统计和扫描成本，具有协同关系；效果仍需单独归因。

~~~mermaid
flowchart TB
    S["Source 准备与 FirstSeen"] --> J["HashJoin：正常选边与分布优化"]
    T["Target：按实际依赖投影"] --> N["合格扫描提供原生 P 路"]
    N --> G["Merge 局部统计保护"]
    G --> J
    J --> C["Action 与已有条件判断"]
    C --> M["汇合后按需补旧字段"]
    M --> W["已有 writer 与提交"]
~~~

图中补旧字段节点只在 Clate 启用。Ccore 继续早读必要旧字段。CollectLeft 场景共享一份 build；Partitioned 场景保留正常按键交换；writer 的最终单分区要求仍然存在。图不表示所有 join 都采用 CollectLeft，也不表示所有重分发都能删除。

首轮范围如下：

| 机制 | 首轮支持范围 | 范围外行为 |
| --- | --- | --- |
| source 准备与初始选边 | 新 reader / materialized-batches 入口、非索引 create_plan | 任意复杂 execute_provider 保留既有处理 |
| StatsGuard | 可可靠定位的外层 merge HashJoin 的真实 target child | 不修改 source 自己的 join；无法识别时记录跳过 |
| native scan | 无序、普通 v2 AllRows、已解析预算、无特殊扫描组合 | 保留现有单输出内部并行，正常 DF 优化继续 |
| late payload | 非索引 RewriteRows，source 确有遗漏旧字段，类型/lineage 契约已覆盖 | Early；RewriteColumns / full source 不冒算新收益 |

“回退”只是某项新能力没有接管，不能表述成回退路径已经获得全进程内存保证。索引路径、外部 hash join、新的全局内存分配器、跨版本 row-address 协议均不在本次原型内。

## 3. Source 准备：只把完整观察写入统计

### 3.1 一个准备结果携带数据与证据

建议新增内部 PreparedMergeSource：

~~~rust
struct PreparedMergeSource {
    provider: Arc<dyn TableProvider>,
    schema: SchemaRef,
    evidence: SourceEvidence,
    allow_replay: bool,
}

enum SourceEvidence {
    Complete { /* EOF、FirstSeen 状态、完整行数及 Arrow 记账 */ },
    Prefix {
        observed_rows: usize,
        observed_batches: usize,
        accounted_arrow_bytes: usize,
        stop_reason: PrefixStopReason,
        before_first_seen: bool,
    },
    ProviderStatsOnly,
}
~~~

PrefixEvidence 只用于内部决策与诊断。不能把 prefix rows / bytes 写成 Precision::Inexact 的全量统计：DF 对 Exact 和 Inexact 都会取出数值比较，并不把后者理解为下界。[JoinSelection][S3]

本次 operation 先解析资源配置，再派生以下数值一次。不要准备阶段使用默认 SessionConfig，执行阶段另读环境与 pool。

| 参数 | 首轮实验初值 | 作用 |
| --- | --- | --- |
| Bpref | min(100 MiB, Mpolicy / 8) | 累计 Arrow 记账停止条件；沿用 B 的 100 MiB 上限并响应小 pool |
| Rpref | 本次 session 对应的行数门槛，默认 128 Ki 行 | 限制极窄多行输入与 FirstSeen 的前置工作 |
| Kpref | 1024 batches | 限制零行/细碎 batch 和元数据工作；能覆盖 100 个单行 batch |
| replay memory_limit | 同一个 Bpref | 小 pool 时更早使用既有重放文件 |
| 小 target 的分类阈值 Bsmall | min(32 MiB, Mpolicy / 4) | 用于第 5 节的规划模型，不是内存准入保证 |

Mpolicy 是按原请求解析出的名义 pool 大小，正常 C 中等于实际有界 DF pool 限额。Cprep∞ 的纯 pool 消融只换 pool 实现，仍使用同一个有限 Mpolicy 派生参数，避免同时改变输入和扫描策略。真实无有限配置的外部入口不纳入本次新策略；不能对“无穷”机械除法。

1024 和 32 MiB 是首轮待校准的设计初值，不是行业常数。正式计时前冻结，不能看到结果后移动阈值包装成功。

### 3.2 精确的停止与重放合同

执行顺序为：捕获 reader schema；完成原有写模式、schema、lineage 等可提前做的参数校验；在字节/行/batch 停止条件下取下一批。只有实际观察到 EOF，才将完整 batches 暴露成有完整统计的 MemTable。

字节/行条件保留 B 的跨限 batch 行为：拿到 batch 后才知道超限，将整批保留并停止继续取下一批。记账包含这批，以 checked / saturating 算术避免溢出。Kpref 则在收到第 1024 批后停止；即使源恰好只有 1024 批，未观察 EOF 也必须保留 streaming。边界少拿到完整统计属于可接受的优化机会损失。

超限回退按原顺序接回“已读 prefix + 跨限批 + 未消费尾流”，每一行恰好一次。中途源错误保留原错误及错误链。空 reader 使用自己的 schema；不能让空 Vec helper 改成 dataset 全 schema。

没有新增 wall-clock deadline。一次 next().await 可以等很久，1024 个 batch 也不是 1024 次 poll；同步阻塞的 producer 更不能由事后计数抢占。慢源的准备屏障必须单独测量，不能声称有限 batch 数保证低启动延迟。

B 的既有实现和重放合同见 [B source preparation][S4]。缩小 replay memory_limit 会改变落盘量、延迟和资源错误时机，但不改变 retry 授权、重放顺序或内容。allow_replay / spill_for_retry(false) 仍决定是否允许重试；MemTable 能重读不等于自动扩大重试范围。

### 3.3 FirstSeen 与内存口径

只有原始输入在预算内 EOF，才完成小输入的顺序 FirstSeen 并对去重后的 batches 建统计。未 EOF 的流继续既有顺序去重；原始 prefix 的大量重复行不能证明去重后的 build 很大。

源预读的行数与字节限制也不是 FirstSeen 的完整 distinct-key 集合上限。原有流式去重集合可能继续随不同键数增长，这一状态须记录，不能归入“已由 Bpref 严格限制”。

get_array_memory_size 的加和、replay 的记账和进程 RSS 不是同一个量。Arrow slice 可保留更大的 backing allocation，一个 caller batch 也可能独自超过 Bpref。两个阶段使用相同 Bpref 不构成两个相等的物理驻留上限。

## 4. StatsGuard：避免未知宽度被小行数误判

### 4.1 为什么必须同时处理 rows 与 bytes

冻结 main 已使用 estimated_total_byte_size，并把宽度估计标为 Inexact。问题在于宽字段估计仍可严重偏低，而 DF 仍用这个数值决策；并非再把 Exact 改成 Inexact 就能解决。[扫描统计与宽度估算][S6]、[宽度工具][S8]

仅把变长 target bytes 设为 Absent 仍不够。明确反例是：

- source 首批 25 × 10 MiB，跨过 Bpref，未见 EOF，完整统计未知；
- target 实际投影 200 × 5 MiB，约 1 GiB；
- 如果 target 仍报告 Exact(200) rows，DF Auto 会因 200 小于行数门槛，单侧判断 target 可 collect，主动将其交换到 build；
- 该交换不需要知道 source 总行数。[单侧 collect 规则][S3]

首轮主案因此是：对实际 target 投影中未能建模宽度的字段，同时向 DF 省略 total_byte_size 和 num_rows。原始统计保留在内部 evidence 和日志中，不改写成假的行数或巨大 bytes。

### 4.2 只在本次 merge 的实际 target child 上生效

建议在 MergeInsertPlanner::plan_extension 识别外层 merge HashJoin 后，给真实 target child 包 MergeTargetStatsGuardExec。不要修改全局 Lance 扫描统计，也不要按 dataset 全 schema 永久分类。

固定宽 primitive、Boolean、Null、合法 FixedSizeBinary 可进入首轮固定宽模型。Struct / FixedSizeList 只有递归模型、bitmap 和长度处理被测试覆盖时才加入。Utf8/Binary 及其 Large/View、普通 List/Map、Dictionary、未识别 extension 均视作未建模。Dictionary 的 key 固定宽不代表 values 固定宽；blob descriptor 也须按实际输出字段判断。

full-source upsert 可能只从 target 读取 keys / row identity。即使 dataset 有宽 payload，这个实际投影仍可完全固定宽，必须保留其统计，否则 reverse 优势会被误伤。

未建模时：

~~~rust
let mut stats = child.partition_statistics(partition)?.as_ref().clone();
stats.num_rows = Precision::Absent;
stats.total_byte_size = Precision::Absent;
~~~

固定宽时返回原统计，保留原来的 Exact / Inexact 精度，不把模型升级成 Exact。Guard 的代价也要写进提案：为了避免 DF 用行数判定容量，局部省略了本来可靠的 cardinality，因而会损失一些成本优化机会。

### 4.3 Guard 不能被统计框架绕过

DF 54.1 的内置 StatisticsRegistry 会对单 child、CardinalityEffect::Equal 的透明算子直接复用 child 统计。照抄普通 wrapper 的 Equal 声明会绕过上述保护。[StatisticsRegistry][S9]

首轮 Guard 保留默认 CardinalityEffect::Unknown，不提供 downcast_delegate，让内置 registry 使用 Guard 自己的 masked statistics。这是不承诺统计透传，执行仍原样转发每一行。需要 registry 开/关的机制测试。

Guard 必须正确转发执行属性、分区编号、顺序及重建/reset，并核验 native repartition、必要 projection、filter/dynamic-filter 相关 hook 没有被阻断。不要给它新增数据队列。这里是本设计最大的集成风险，必须在性能实验前解决。

逻辑优化已裁掉宽字段时，首次分类必须识别固定宽。更晚的物理 projection 若裁掉宽字段，首轮允许暂时保守保留 masked 状态，并记录损失的机会；若实现投影交换以恢复统计，须在新 child schema 上重新计算，不能用旧布尔值。普通 Projection 不会从双 Absent 凭空恢复 rows。[DF projection/statistics][S16]

如果 Guard 的 forwarding 成本或优化阻断难以控制，应修改接口放置方式；不要用关闭整个 join_reordering 来“修好”它。面向 DataFusion 的长期更合适接口是分开表达 cardinality、size confidence 和 collect eligibility，本原型不假装该接口已经存在。

## 5. 初始选边：默认 source，给可信的小 target 留出口

### 5.1 决策发生在分布优化前

将 SourceEvidence 作为现有 MergeInsertPlanner 的私有字段。在处理 MergeInsertWriteNode 时，沿允许的一元 Projection/Filter 链定位外层 merge join，以 logical source/target 身份、join keys、source sentinel 和 target 行身份交叉核对。

不能搜索“任意 Full HashJoin”并改向。merge 可产生 Inner / Right / Left / Full，source provider 自己也可能包含 join。任意复杂 provider、非 HashJoin、不可 swap 或无法可靠定位的结构不接管，明确记录原因。[现有 extension planner][S10]

先取得 unguarded target 的实际 schema / 全局统计，再包 Guard、选初始方向。如需交换，使用公开 HashJoinExec::swap_inputs(PartitionMode::Auto)，由它恢复 join type、键表达式、过滤与输出次序；随后完整运行正常 physical optimizer。不关闭 join_reordering、repartition_joins 或全局 RoundRobin 开关。[DF HashJoin API][S5]

### 5.2 确定的首轮规则

对固定宽 target，N 是 Exact 全局行数，W 是实际可见每行宽度模型，含 bitmap。首轮使用：

~~~text
Mmodel = 2 * N * W + 64 * N + 1 MiB
Bsmall = min(32 MiB, Mpolicy / 4)
~~~

双份 payload 给收集与 concat 并存留余量，64N 为 hash/索引/scratch/bitmap 留粗粒度余量。该式只是可复核的规划启发式，不是已证明的完整 build 上界。实现可复用 DF 哈希容量函数替换其中的 hash 部分，但仍必须计入其他状态。[DF hash build][S5]

| Source 证据 | Target 证据 | 初始方向 | 后续处理 |
| --- | --- | --- | --- |
| 完整 EOF，FirstSeen 需要时已完成 | 任意 | source-left | 固定宽双方让 DF 比较；未知宽 target 由 Guard 撤回不安全提示 |
| 未 EOF | 实际投影固定宽、Exact 全局 rows，Mmodel ≤ Bsmall | target-left | 押注已有证据的小目标；Auto 可用 CollectLeft 或 Partitioned |
| 未 EOF | 不满足小固定宽条件 | source-left | 保留正常优化器；对未知宽 target 不提供 row-based collect 入口 |
| FirstSeen 仍 streaming | target 满足小固定宽条件 | target-left 可用 | 理由来自 target；不能用 raw prefix 强化去重后规模结论 |
| 入口/结构不支持 | — | 原路径 | 明确该原型没有覆盖 |

这里不要求 prefix 证明 source 比 target 大，才允许 target-left。否则细碎 batch、FirstSeen、慢源都可能让 reverse 出口失效。代价是：一个最终很小但很慢的 source，也可能先构建 100K 行的已知小 target。有限观察无法同时保证总选出更小侧和不等到输入结束。

### 5.3 Reverse 的可解释路径

100K target / 真实 lazy 3M full-source，若实际 target child 只有固定宽 keys / row identity，规划模型足够小，则 unknown source 触发 target-left。target bytes 超过 DF 默认 collect 门槛时，可以选择 Partitioned；仍是 target build，并不要求强制 CollectLeft。

这要由实际计划和 1 GiB pool 下的 execute 证明。原有 B 的成功不能替新 C 作证。若 target 是变长 key 或仍须携带未知宽 payload，Guard 会撤回其大小，Ccore 不保证保住该变体；Clate 缩窄旧 payload 后可能改变分类，但不会解决变长 join key 本身。

## 6. 资源设置：先固定池，再统一 P

### 6.1 解析顺序

Lance 默认 pool 配置可随目标分区数按 150 MiB × T 变化。因此先按原请求 T 解析 Mpolicy，再固定 mem_pool_size: Some(Mpolicy)，最后推导有效 P 并创建同一次 operation 使用的 SessionContext。否则减少 P 时会再次改变默认池大小，消融也失去可比性。[Lance context][S13]

正常 C 使用现有有界 pool。planning、execute、条件节点和 writer 使用一致的实际上下文；独立 analyze 可以有自己的实例，但有效配置必须相等。retry 针对新 target snapshot 重建扫描运行态并重算 target 证据，不复用已消耗的任务流。

不要假设整个进程都向 DF pool 登记了分配；也不要把 use_spilling 理解为 HashJoin 会自动溢写。这里复用的 HashJoin 在 pool 不足时可能返回资源错误。[DF hash build][S5]

### 6.2 扫描的首轮公式

~~~text
T           = 原请求的 session target partitions
Ndecode     = 原 scanner batch_readahead 上限
Mpolicy     = 按原 T 解析并固定的名义 pool bytes
I           = min(max(Mpolicy / 4, 16 MiB), configured_io_bytes)
Bdecode     = Mpolicy / 4

Pmem        = max(1, floor(Bdecode / max(width_est, 1)))
P           = max(1, min(T, Ndecode, Pmem))
rows_goal   = max(1, min(existing_row_cap,
                        floor(Bdecode / (P * max(width_est, 1)))))
~~~

I 的公式来自 #10077，Bdecode 和先限制 P 是本候选的扩展。I 与 Bdecode 是不同资源的软目标，不能相加后声称已经从 DF pool 硬划走这部分内存。[#10077 MergeBudget][S14]

width_est 优先使用预计 target 投影的固定宽内存模型；创建 context 前可按 keys、缺失旧列、row identity、必要 lineage 推导保守字段集合。它只服务成本估算，不手工覆盖实际 projection pushdown。变长数据可退到已有文件 bytes / physical rows 的均值，但它是磁盘口径，压缩、偏斜和嵌套开销都可能使其低估内存。记录估值来源。

如果 width_est 完全不可得，native 资源策略不接管：P=min(T,Ndecode)，使用旧单输出扫描，标记“没有宽度约束的回退”。如果单行已经超过 Bdecode，P=1、rows_goal=1 也只是减少并存大行，无法让这一行变小。

existing_row_cap 采用 FilteredReadExec 的真实 v2 配置解析：显式值、环境配置及对象存储/reader 默认，不能用 DataFusion session batch size 冒充。configured_io_bytes 同样尊重现有显式值、环境和 scheduler 默认。现有 I/O 值 0 表示关闭字节背压，首轮对此回退原语义，不能把它解释为零字节上限。[扫描 options][S6]、[scheduler][S15]

### 6.3 内外优化器必须使用同一个 P

Lance Scanner 自己还会做一轮物理优化。TableProvider::scan 必须把外层 session 的 effective P 显式传给 Scanner::target_parallelism，同时传 batch_readahead、I/O 和 batch rows。仅在外层设置 P 不够，内层可能已按 CPU 默认值扩分区。[TableProvider][S17]、[Scanner][S18]

新增内部 NativeScanPolicy 持有固定 output_partitions=P 和原 decode_task_limit=Ndecode。FilteredReadExec 只有能提供 exactly P 且 guard 满足才返回原生分区。不能局部返回更小路数，再让 DF 用 RoundRobin 补回 P。[DF 分布优化][S7]

这一改动保持正常分布优化。预算不同导致 P 下降是一项有意的资源策略；同 P 的 Cbudget 对 Ccore 才用于识别原生拓扑收益。

## 7. Native scan：共享现有运行态，避免按 P 扩张窗口

### 7.1 首轮资格

native 只在本次 merge target 明确允许无序时开启内部 opt-in，并要求：

- 普通 v2 AllRows；没有 RowSet / RowStream；
- 没有 before/after range、特殊 filter/refine/row-address prefilter 或预计算扫描 plan；
- 没有 batch_size_bytes rechunk、稀疏 consolidation、Blob v2 binary materialization；
- 普通排除已删除行的扫描允许，with_deleted_rows 调试模式回退；
- 资源验收先限定 primary-base、无 overlays；
- width_est、P、Ndecode、rows_goal、I 均已解析。

这些条件为首轮集成范围，不是对其他扫描模式的永久限制。不能删掉真实条件来满足 guard。正常 target 条件继续在已有 deferred-condition 层处理。

### 7.2 接口行为与资源所有权

在现有 ExecutionPlan::repartitioned 中检查 opt-in、配置 P 和上述条件，然后 clone 只读 options，将 threading_mode 改为 MultiplePartitions(P)，通过现有构造器生成新的 exec。新 exec 应有新 properties、metrics、plan cell、running_stream；同一 exec 的 P 路共享一次初始化，不为每路重建整个扫描。

原生模式每路领取一个 read-batch task，在共享任务流的锁外 await。原来 OnePartitionMultipleThreads(N) 则用内部 buffered 窗口。保持 P≤Ndecode，不给每个原生分区再套 buffered(N)，可以控制这层同时推进的批任务数。[扫描运行态][S6]

普通 AllRows 的 P 路共用 primary ScanScheduler、BaseSchedulers cache 和 fragment_readahead，I/O 配置无需除以 P。每个独立 base 的 scheduler 额度仍然独立，因此首轮 primary-base guard 很有意义；它没有暗中实现跨 base 总额度。RowStream、rechunk 等路径会引入不同的逐路缓冲，首轮回退。

target 最终成为 build 时，允许 native scan 后接 Coalesce。repartitioned 不知道父节点或 join side，不能把它包装成严格 probe-only 能力；本方案不为此再规划一次。

### 7.3 全局统计、完成和输出分布

动态领取任务不会保证每路等分。partition_statistics(None) 保留扫描原本可证明的全局 Exact；Some(i) 的 num_rows 改为 Inexact 或 Absent，不能报 Exact(total/P)。相关 bytes 也不能更精确。[扫描统计][S6]

CollectLeft 的 P 路 probe 共享 build，最后一个完成的 probe 才能处理某些 outer join 的剩余 build 行。所有声明分区都必须正常耗尽，包括未领取到任务的空分区；某一路错误或取消不能当作完整匹配后提交。[DF HashJoin][S5]

最终 writer 的 SinglePartition 继续由正常分布优化满足。目标是去掉 target scan 到 probe 之间仅为增加路数而插入的 RoundRobin；按键 HashPartitioned 交换和 writer 汇合仍保留。

### 7.4 本版资源承诺的精度

可以直接验证的承诺是：相同 P / 配置下 scheduler 初始化不按 P 复制，fragment 窗口不乘 P，不出现每路 buffered(N)，实际同时推进的批任务符合既定上限。

I/O scheduler 为了前进允许部分请求越过字节目标，其额度释放也不跟随下游 Arrow backing buffer 的最后一次释放。因此 I 不是 RSS 限额，Bdecode 也不是按实测 bytes 做准入；一个 task 内还可能涉及多文件、编码页和中间数组。[scheduler][S15]

Mpolicy、I、Bdecode、Bpref 的合计不能当成进程峰值公式。调用者输入、去重状态、writer、条件 Take 和晚补列 Take 都可能并存。ECS 分别记录 DF reservation、RSS 和 cgroup charge，不制造一个不存在的全局 credits 系统来解释它们。

## 8. Clate：在 action 确定后补旧字段

### 8.1 这项优化真正减少什么

适用条件是非索引 RewriteRows，source 遗漏至少一个 target 列。目标首读 keys、_rowaddr、_rowid 和必要 lineage；旧 payload 不因最终写整行就全部提前进入 join。

修改 fill_missing_target_columns 和 MergeInsertWriteNode::necessary_children_exprs 的依赖表达，用 DeferredTargetColumns 明确声明“这些字段由 writer 前的新节点生成”。仅删除 scan projection 会违反现有 writer 的完整 schema 合同，不能算实现完成。[logical plan][S10]、[writer][S12]

### 8.2 节点顺序与第一版取舍

首轮把新 MergePayloadExec 放在已有 MergeConditionExec 之后、最终 Coalesce 之后、FullSchemaMergeInsertExec 之前。新节点要求 SinglePartition，逐 batch 串行发起一次 payload Take，避免直接新增 P 份 payload Take 并发。

现有 MergeConditionExec 可以只读取输入尚无的 target 条件列，并把失败行的 action 改为 Nothing；它不会自动将取回的条件列继续输出给 writer。首轮复用它的语义，允许条件与 payload 重叠时发生二次读取，并单独记录这项成本。若它主导退化，再做共享列结果的独立优化，不把未经测试的缓存协议塞进首个原型。[condition][S11]

这会新增一个按批的晚补列开销和可能的串行瓶颈；C 的 scan/probe 并行仍在前段保留。只有其节省的 payload 工作足以抵偿 Take 成本，才值得采用。

### 8.3 每类 action 的合同

| Action | 是否取旧 payload | 必须保持的结果 |
| --- | --- | --- |
| 匹配且实际 UpdateAll | 取 source 遗漏字段 | 按该物理 target 地址取值并回填原行位置 |
| Insert，source-only | 不取 | 行不能因空 target 地址被删除；缺失 nullable 字段按原语义填 NULL |
| Delete | 不取 | 保留地址与身份，交给既有删除处理 |
| Nothing | 不取 | 不发生 payload 读取，不改变 action |
| Fail / 源错误 / Take 错误 | 不为补列而绕过错误 | 保持失败传播，本 attempt 不提交 |

插入遗漏不可空字段的错误继续在源消费前校验，不发明默认值。中间 batch 的 nullability 应符合 merge 中间 schema：未写出的 action 可使用合法的 nullable 占位列，不能在声明 non-null 的字段中塞 NULL，或为满足 schema 反过来读取无用 payload。写出前应恢复与 early 路径等价的有效行值和 writer 类型合同。

Take 必须使用同一 Arc<Dataset> snapshot 和匹配产生的 row addresses。不能按 join key 回查，因为不同 target 行可有相同 key、不同旧字段。批内 gather/reorder 后要恢复原行位置；地址数量不符时错误退出。retry 重做匹配并使用新 snapshot，不能沿用旧 rowaddr。

不要把通用 RowStream Take 直接套在 outer join 后；当前路径会丢 null/stale key 行，source-only insert 会受影响。[Take/attach_read_columns][S6]

首轮 Late 范围先覆盖普通可直接 Take 的 Arrow 字段与现有 lineage 组合。嵌套/blob 表示或 lineage 不能原样恢复的组合显式回退 Early；只有补齐语义测试后才能扩大。

### 8.4 先提供强制 Early / Late，不新增未证实的 Auto

内部实验模式在规划前确定。运行中已扫描一半后再切换 Early 涉及重扫、状态与地址协议，本轮不实现。

必须测两个方向：宽列稀疏更新，以及少数热 key 命中约 90% 物理行、覆盖大量页的高覆盖场景。后者 Late 可能比 Early 更慢，特别是随机 I/O 成本高、条件与 payload 重复读取时。

如果没有可靠的动作选择率、页覆盖和 I/O 成本信息，交付 force 模式及适用结果，保留 Early 默认。不能把“source=100”作为自动 Late 的充分条件。若只在稀疏本地负载占优，最终 proposal 应如实限定结论；未经远程实验不外推到对象存储。

## 9. 改动地图与实施次序

| 模块 | 需要的改动 |
| --- | --- |
| rust/lance/src/dataset/write/merge_insert.rs | PreparedMergeSource；资源统一解析；source/replay/FirstSeen 参数传递；实际 context 复用；Late 依赖元数据 |
| 同目录 merge_insert/logical_plan.rs | 初始 join 定位与安全 swap；StatsGuard 注入；DeferredTargetColumns；插入晚补列节点 |
| 新的 merge 局部 StatsGuard 模块 | masked statistics、属性/优化 hook 转发、重建/reset、诊断原因 |
| rust/lance/src/datafusion/dataframe.rs | 内部 native / I/O / batch 策略接线；把 session P 传给 Scanner |
| rust/lance/src/dataset/scanner.rs | 传 native eligibility；使用统一 P/N/rows/I；保留顺序约束 |
| rust/lance/src/io/exec/filtered_read.rs | repartitioned 接口；资格检查；新运行态；修正分区统计 |
| merge_insert/exec/ 下新 payload 节点 | 单流按 action 取旧列、回填、schema 与错误合同 |
| 现有 Rust/Python 测试与实验 harness | 有意义的语义/机制测试、真实 lazy source、逐行 oracle、内部消融开关 |

以上路径来自冻结源码，Codex 仍需在实际 checkout 核对方法与 API；本稿中的新类型不是现成可调用接口。首轮不要求大改 HashJoin 本体，不修改索引/列重写路径来凑收益，也不新增公开 Python 调优旋钮。

实施顺序：

1. 统一 context、source evidence、StatsGuard 和初始方向；先通过宽目标错误 collect 与 reverse 的机制检查。
2. 接通预算和 effective P；在关闭 native 的现有 v2 OnePartitionMultipleThreads 扫描路径记录 Cbudget。
3. 接 native，验证完整计划和共享运行态，再进入核心计时。
4. 实现 Late 的依赖/执行合同，用 Early/Late 验证实际读取量与行为。
5. 依据相邻比较决定最终保留哪些机制，再整理一个连贯 upstream proposal。

这是一组可审查的实施与实验步骤，没有预设“统计必须先合入”。

## 10. ECS 怎样判定这份设计是否值得继续

配套 codex-ecs-validation.md 给出完整 workload、runner、状态、资源测量与执行顺序。这里冻结关键决策：

| 问题 | 必须拿到的证据 |
| --- | --- |
| 防止目标宽度误判是否真正生效 | 未知 source + 200 行巨大 target，registry 开/关均不因 row-based collect 误建 target |
| 是否保住 B 的适应性 | 100K target / 真实 lazy 3M full source，在 1 GiB pool 下执行成功并逐字段验证 |
| native 是否减少了预期中间环节 | 同 P / 同扫描配置的 Cbudget 与 Ccore，最终 target probe 路径无额外 RR；build 只建立应有次数 |
| 并行是否复制了资源窗口 | 一个 exec 的共享初始化、实际批任务峰值、scheduler 数与错误/取消行为 |
| Late 是否减少实际工作 | 同 snapshot 的 Early/Late 等价；宽列读取 bytes/请求数/驻留有对应变化 |
| 高覆盖率是否反驳默认 Late | 目标重复 key，逐物理行 oracle，不能以 source key 数代替更新行数 |
| 是否只把 OOM 换成错误 | 分开统计 workload 成功、ResourcesExhausted、确认 OOM；不把安全拒绝记作成功 |

采用相邻消融：Cprep∞ 只做小型纯 pool 诊断；Cprep → Cbudget → Ccore；Clate 与相同资源的 Early 配对。U/B/P 原样保留作工程参照，不用整包差异归因某一个开关。

核心正式比较先做随机配对 3 块，再补到 5；必要时最多 9。首轮建议 native 相对同预算 Cbudget 有至少约 10% 稳定中位 wall-time 改善，才足以抵偿新增接入复杂度；这是预注册工程门槛，不是显著性保证。已物化输入、reverse、skew、FirstSeen 有稳定超过 10% 退化时先解释，不扩大矩阵掩盖问题。

如果 native 正确但没有值得保留的收益，继续用 Cbudget + Late 检验 payload 方向。只有具体问题需要时新增这一比较，不枚举全部开关组合。任何组件都不因曾被推荐而自动进入最终方案。

F4/F16 核心与反例通过后才扩到 F64、cold cache 或已授权对象存储。不要直接重跑全部历史 160 次矩阵。

## 11. 可预判的收益、代价与停止条件

最可能直接修正结构的是双 Absent Guard 与初始方向：它们消除已知宽目标错误 collect，同时给固定宽小 target 留出明确路径。最需要实测的部分是 Guard 对其他优化的影响。

native 的收益取决于旧分发/队列成本与 probe 工作量。它可能让 B 更接近 P，但 P 的优势也可能主要来自其他预算设置；Cbudget / Ccore 的相邻比较会回答这一点。

Late 在宽列稀疏更新中有更高的收益上限，因为它减少需要读取和解码的数据量；在高覆盖率或高随机读取代价的环境中也更容易退化。它不是依赖 source 行数就能安全默认开启的优化。

仍未解决的区间包括：两侧真正都放不进 hash build 内存、未知大 source 对实际很小但宽度未建模的 target、流式 FirstSeen 的大 distinct-key 状态、调用者单个巨大 batch、扫描/Take/writer 未统一记账的驻留。把这些边界写清，比承诺一个现有接口无法提供的 RSS 硬上界更有工程价值。

停止扩大或修改设计的条件：

- 任一支持场景出现错误结果、重复/丢行、FirstSeen winner 改变或失败提交；
- Guard 在实际优化器配置下失效，或明显阻断必要优化；
- effective P 被内外层重新扩大，native 配置引入逐路窗口复制；
- reverse 只能通过提高资源额度才能恢复；
- 某项新增复杂度没有稳定收益，或仅靠换写模式/NoOp 才出现好成绩。

ECS 完成后，提案应陈述“哪些场景、同样什么资源、为何更好，以及哪里仍有代价”。届时再决定在 #9505 继续讨论还是开一个同时关联 #9505 / #10077 的设计 issue。本任务没有授权发布 upstream 内容。

## 参考源码与既有证据

[S1]: https://github.com/easyrev/lance/blob/3fd5356239b91c0d38e818b0c7237e9545d1db11/review/issue-9505/README.md
[S2]: https://github.com/easyrev/lance/blob/3fd5356239b91c0d38e818b0c7237e9545d1db11/review/issue-9505/REPORT.md
[S3]: https://github.com/apache/datafusion/blob/54.1.0/datafusion/physical-optimizer/src/join_selection.rs
[S4]: https://github.com/easyrev/lance/blob/793e4e27119540a17ae37ce78d4f5f4d52060a93/rust/lance/src/dataset/write/merge_insert.rs
[S5]: https://github.com/apache/datafusion/blob/54.1.0/datafusion/physical-plan/src/joins/hash_join/exec.rs
[S6]: https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance/src/io/exec/filtered_read.rs
[S7]: https://github.com/apache/datafusion/blob/54.1.0/datafusion/physical-optimizer/src/enforce_distribution.rs
[S8]: https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance/src/io/exec/utils.rs
[S9]: https://github.com/apache/datafusion/blob/54.1.0/datafusion/physical-plan/src/operator_statistics/mod.rs
[S10]: https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance/src/dataset/write/merge_insert/logical_plan.rs
[S11]: https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance/src/dataset/write/merge_insert/exec/condition.rs
[S12]: https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance/src/dataset/write/merge_insert/exec/write.rs
[S13]: https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance-datafusion/src/exec.rs
[S14]: https://github.com/lance-format/lance/blob/9e1ebc2e816a7195b56757ebe269e74989fc30c7/rust/lance/src/dataset/write/merge_insert.rs
[S15]: https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance-io/src/scheduler.rs
[S16]: https://github.com/apache/datafusion/blob/54.1.0/datafusion/common/src/stats.rs
[S17]: https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance/src/datafusion/dataframe.rs
[S18]: https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance/src/dataset/scanner.rs

