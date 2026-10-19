# #9505 机制与维护成本对照

本文件比较统一基线 `0a0d327082988018a25f56147d3b6d02f6c79ecc` 上的 B、P、D、CTX、DB、DP。结论来自本轮 `ports/*/source` 和原设计源码审查；这里不使用尚未完成的性能实验判定胜负。B 来源为 `793e4e27119540a17ae37ce78d4f5f4d52060a93`，P 来源为 #10077 的 `9e1ebc2e816a7195b56757ebe269e74989fc30c7`，D 来源为 `50e216972e1558ce253bece5db462d8241fde96a`。CTX 只提取 D 的 context 修改；DB、DP 分别组合 D+B、D+P。原设计的历史统一候选 C 与本轮 CTX 是不同对象。代码量对应 `cost-audit.json` 内逐文件 source/patch hashes；后续源码若为构建或测试修正而变化，须重新运行计数，不把此快照当成最终二进制身份。

## 1. 先把要付的工作分开

一次非索引 merge 先匹配 source 与 target 的 key，产生更新、插入、删除或无操作的 action，再写出实际结果。HashJoin 的 build 侧需要保留进入该侧的行及实际投影字段，另建 hash/索引、必要 bitmap 和拼接缓冲；probe 侧逐批匹配。Rows writer 对更新行最终仍要写完整行，source 没有提供的旧字段必须从 target 取得。晚取旧字段可以减少匹配前的读取和驻留，但不会消除完整新行的写入。

用 `N_s/N_t` 表示实际进入 join 的 source/target 行数，用 `W_s/W_t` 表示该节点真正保留的字段宽度，而不是 dataset 全 schema 的宽度；用 `U` 表示条件通过后实际更新的物理 target 行数。选边主要改变被长期保留的 `N × W`，late payload 主要改变 target 的 `W_t` 及旧字段从“匹配前读”变成“按 U 对应地址读”。少数 source keys 可以命中大量重复 target 行，因此 `N_s` 小不能证明 `U` 小。页覆盖、地址局部性和存储请求延迟还会决定 Take 的代价。

三类内存必须分别记录：DF pool 中登记的 reservation；没有登记到该 pool 的 source 前缀、scan/decode/Take/gather 等数组与队列；进程及 cgroup 实际占用。设置 `use_spilling=true` 并不把 HashJoin 变成外部 hash join：DF 54.1.0 的 build 路径逐批 `try_grow`，超出 reservation 能力时会返回资源错误。[DF build 记账](dependency-excerpts/hash-join-build.md)

## 2. 原设计目标与本轮实际实现

原设计希望同时解决小 source / 大 target、反向大 source / 小 target、未知宽字段误判和扫描并发窗口，并把 native scan 与 late payload 分别消融。它包含的部分机制本轮没有实现，不能以 DB 或 DP 的名称代替原设计完成证明。[原目标与改动地图](inputs/lance-9505-unified-design.md)

| 原设计项目 | 原设计的具体合同 | 本轮对应状态 |
| --- | --- | --- |
| source 准备 | 仅 EOF 发布完整统计；字节预算 `min(100 MiB, Mpolicy/8)`，另有 rows、1024 batches，retry 缓冲使用同一预算 | B/DB 只有原始 100 MiB + 新建 SessionConfig 的默认 131,072 rows 阈值；没有 pool 派生预算、batch 上限或新 replay 预算。P/D/CTX/DP 不增加 EOF 预读 |
| 未知统计与选边 | target 实际投影宽度未建模时局部撤回 rows/bytes；未知 source 给可信小 target 留选边出口 | 所有本轮版本都没有 StatsGuard。B/D/CTX/DB 保留 DF Auto；P/DP 固定 source build。已删除的 heuristic selector 不属于 D |
| 扫描资源 | 先固定 pool，再统一内外有效分区数；优先按实际投影宽度估算 rows | P/DP 使用原 P 的 I/O 和整表磁盘均宽批次公式，并保留单路 probe；其余版本未增加 scan budget 策略 |
| native scan | 合格 AllRows scan 原生提供多路输出，共享 scheduler/任务流，避免额外 RoundRobin | **本轮六个版本均未新增这项能力**；基线已有的扫描内部并行或 MultiplePartitions 接口不能算本轮成果 |
| late payload | 初版建议单独节点、Coalesce 后串行补列；允许条件与 payload 二次读取；先强制 Early/Late 对照 | D/DB/DP 合入已有 condition 节点并复用条件值，继承输入分区、每分区串行分块；没有 force Early/Late API，符合类型/写模式资格即启用，未加覆盖率收益门槛 |
| 统一 context | 同 attempt 规划与执行使用一致实际上下文；没有全进程硬限承诺 | 非索引 v2 路径：CTX/D/DB 共用同一 session 的 task context；DP 共用 P budget 的 task context。纯 B 保留分开的 bounded contexts，纯 P 的 execute 共用，analyze 仍另建实例；这不是所有外围路径共用一个 pool 的声明 |

原设计关于宽度模型、native 的共享运行态和 force Early/Late 的合同见[扫描及 late 设计](inputs/lance-9505-unified-design.md)。本轮是对已有机制的统一基线比较，不应写成完整实现了该原设计。

## 3. 每个版本实际保留什么

下表的选边描述针对普通非索引 v2 merge 的 source/target join；不把 provider 自带的子计划、indexed 手工 join 或 legacy/Columns 全部概括成同一执行计划。

| 版本 | source 的行与字段 | target 的行与字段 | join / scan / 缓冲 | 具体新增失败边界或未解决边界 |
| --- | --- | --- | --- | --- |
| B | 尝试读到 EOF；完整小输入保留全部 source batches，提供完整统计。FirstSeen 的小完整输入顺序去重后再 materialize；跨限时保留整批 prefix 和尾流 | Rows partial update 仍提前补入 source 遗漏的旧字段；没有缩窄这项 target payload | 普通 DF Auto 选边和分布优化，扫描策略沿用基线；准备缓存未登记到 pool | 大 source 支付预读后仍可能没有完整统计；超大首批、空批长流、慢 producer 均没有新的严格上限；target 变长宽度估计仍可能误导 Auto |
| P | 固定 source-left/build，保留该侧全部实际需要的 source 字段与 hash 状态；不会等小流 EOF 取得统计再决定选边 | 单路 probe 流过 target；Rows partial update 仍早读遗漏旧字段 | 关闭 join_reordering、repartition_joins、RoundRobin；scan 内部仍并行 decode；设置 I/O 和 batch rows | 大而宽 source / 小 target 的 reverse 仍必须 build source；pool 可将超限变成资源错误，但业务没有完成；平均磁盘宽度不是峰值内存宽度 |
| CTX | source 内容、消费时机和 provider 与基线相同 | 早读遗漏旧字段，投影与基线相同 | Auto 与 scan 不变，只改 session factory 和 task context 传递 | 从默认无界执行 context 改成项目 bounded context，原来可继续增长的 tracked build 现在可能资源失败；不解决错误选边或未记账数组 |
| D | source 准备与基线相同，没有 B 的 EOF 证据；source 写入字段仍需要进入 join | 合格 Rows 更新将遗漏 scalar 字段移出匹配输入；保留 keys、row identity/address、必要 lineage，随后按物理地址补值 | Auto 可继续 build target；条件和 payload 统一 Take/gather，每分区软分块 | target build 的 key/address/hash 状态仍随 N_t 增长；变长 key 未获保护；高更新覆盖率/散乱地址可能增加 Take 成本；突增值可能超过软目标 |
| DB | B 的完整小输入统计、prefix、FirstSeen 路径保持；不是新 source admission | D 的窄 target 与条件值复用保持 | 普通 DF Auto；同 attempt 使用 D 的共同 pool/context；未增加 native scan | 兼有 B 的准备屏障和 D 的地址/补列生命周期；Auto 仍依赖实际投影统计是否可靠，不能保证总选较小 build |
| DP | 保留 P 的固定 source build，不引入 B 预读 | D 缩窄 target probe，并晚取实际更新旧字段 | 保留 P 的 scan/单路 probe 设置；execute/analyze 改为返回并使用 P 的实际 task context | reverse 的固定 source build 风险完整保留；DP 的 scan rows 仍按整表磁盘均宽估算，可能把已经很窄的 key/address scan 切得过小 |

B 的 EOF、整批越界、prefix+tail 代码见 [source 准备](ports/B/source/rust/lance/src/dataset/write/merge_insert.rs)，小 FirstSeen 的第二次 materialize 见 [FirstSeen](ports/B/source/rust/lance/src/dataset/write/merge_insert.rs)。P 的 source/target 方向与 outer join 类型同时反转，匹配语义仍按 source-only / target-only 的保留需求决定：[join 类型](ports/P/source/rust/lance/src/dataset/write/merge_insert.rs)、[source JOIN target](ports/P/source/rust/lance/src/dataset/write/merge_insert.rs)。

## 4. 资源合同不能省略的细节

**共同 pool 工厂。** B/P/CTX/D/DB/DP 都在相关新路径调用项目既有 factory。正常 spilling 配置使用 `TrackConsumersPool(FairSpillPool)`；显式额度或 `LANCE_MEM_POOL_SIZE` 决定大小，缺省为 150 MiB × 创建 factory 时 options 的有效 target partitions。P 的 `MergeBudget(Some(1))` 先创建 pool，后改 session 分区数，不能用最终的 1 个分区反推 pool 只有 150 MiB。factory 同时设置 sort reservation `min(pool/3,40 MiB)`、既有临时磁盘限额并注册 Lance functions，所以 CTX 对 U 也不是仅换一个 pool 实现的单变量实验。`LANCE_BYPASS_SPILLING` 的既有无界行为保留。在非索引 v2 路径，纯 B 的计划与执行分别取得 pool；CTX/D/DB 返回计划及其 task context；P execute 已共用 MergeBudget，DP 还让 analyze 使用该实际 context。P/DP indexed 路径仍由 `execute_plan(...options)` 另取执行 context；不能把局部统一描述为每次 merge 全链路只有一个 pool。[B 执行 context](ports/B/source/rust/lance/src/dataset/write/merge_insert.rs)、[CTX 返回 context](ports/CTX/source/rust/lance/src/dataset/write/merge_insert.rs)、[DP 返回 P context](ports/DP/source/rust/lance/src/dataset/write/merge_insert.rs)、[P indexed 执行 context](ports/P/source/rust/lance/src/dataset/write/merge_insert.rs)。

**P 的扫描目标。** `I=min(max(pool/4,16 MiB), configured_io_bytes)`；`decode_fan_out=max(1,min(compute_cpus,session.target_partitions))`；用 `I/decode_fan_out` 除以所有 fragment 文件 bytes / physical rows 的向上取整均值，只有结果小于 `BATCH_SIZE_FALLBACK` 才覆盖 batch rows。缺行数或文件大小时保持默认。这个公式没有给 Arrow 分配做 reservation，也没有按实际 projection 计算宽度；同一宽表做 key-only scan 时也可能被缩到很少行。DP 正是容易出现该情况的组合。压缩或偏斜又可能让平均值低估实际内存，所以“过小批次”和“实际值超过软估计”都可能发生。[完整公式](ports/P/source/rust/lance/src/dataset/write/merge_insert.rs)、[DP 仍应用该配置](ports/DP/source/rust/lance/src/dataset/write/merge_insert.rs)。

**D 的物化目标。** 条件只对需要判断的 UpdateAll 与 target-only Delete 候选取值；条件失败改为 Nothing。只有剩余 UpdateAll 读取遗漏 payload，已为 update condition 读取的列直接按原行位置复用；Insert/Delete/Nothing 不为最终 payload 发 Take，输出 nullable 占位。Take 使用匹配时同一 dataset snapshot 的地址；错误传播，重试须重新匹配。[候选和条件](ports/D/source/rust/lance/src/dataset/write/merge_insert/exec/condition.rs)、[剩余更新和复用](ports/D/source/rust/lance/src/dataset/write/merge_insert/exec/condition.rs)。条件依赖目前按 update/delete 的并集取值，不意味着表达式 OR 会逐行短路 I/O；writer 的重复匹配检查仍在后面，也不能宣称每个最终写入行全程恰好只取一次。

payload-enabled 节点以 `pool limit / 8 / 输入分区数` 计算每分区软目标，范围夹在 1 byte 至 16 MiB；没有从 pool 中划拨或预留这份额度。无穷或未知 pool limit 时目标为 16 MiB。固定宽字段先估算，变长字段从一个可 Take 候选起步，再用上一片的观察宽度和 4 倍余量决定候选数，同时限制输出行数。纯 condition-only 节点保持原批粒度。分块串行仅保证本分区不会主动同时发起下一片 Take；输入 backing buffers、storage pages、一次巨值、条件数组与 gather 并存、下游 writer 持有的输出都可超过软目标。观察小值后突然出现大值时也可能放大一片；没有 reservation 或全局 RSS 硬限。[完整分块合同](ports/D/source/rust/lance/src/dataset/write/merge_insert/exec/condition.rs)。

**spill 是几条不同路径。** 既有 source retry spill、可 spill sort/lineage 和 DF pool 资源错误不可混称为“join 自动落盘”。B/DB 的预读 prefix 不会因 pool 设置而自动转为磁盘前缀；其后的既有 retry provider 仍由 allow_replay 管理，能重读不扩大重试授权。D 的 Take 也没有因收到 task context 的额度而自动登记全部分配。TMPDIR 采样只能证明观测到的文件占用，不能据文件存在推导哪个算子已完成外部化。

## 5. 必须单独保留的反例与适用范围

- **P/DP reverse：** source 比 target 大且携带 full schema 时，source 的全部写入字段仍需要 build；D 不会删掉 source 新值，也没有遗漏字段可晚取。小 target 的可靠统计不能使 P/DP 换边，因为相关优化开关关闭。是否在给定 pool 下成功必须实际执行；不能以较小 target scan 或减少 payload Take 证明 reverse 已解决。
- **D 的大 target：** 即使 payload 完全移出 target build，key、rowid、rowaddr、必要 lineage 和 hash 状态仍可随实际进入 build 的 target 行数增长。窄投影能降低每行成本，不能给总行数建立上限。若 key 本身变长，原先的宽度估计风险仍存在。
- **DB Auto：** B 的 EOF 给完整 source 提供真实统计，D 又让 target 统计对应更窄投影，两者可互补；但未 EOF source 仍未知，target 的 bytes 估计也可能不可靠。DF 54.1.0 通过 `get_value()` 使用 Exact/Inexact 数值，bytes 不可得时可退到 rows，并可由单侧 collect 资格换边；当前没有 StatsGuard 撤回不可靠提示。[DF 比较及 collect 规则](dependency-excerpts/join-selection.md)
- **D 的高覆盖率：** eligibility 是正确性/表示合同，不是性能选择器。合格类型在高覆盖率场景仍会晚取；90% 更新、少数重复热 key、大量离散页、远端小请求都可能消耗额外工作。不能用 sparse 的改善抵消或隐去这些格的退化。
- **类型与路径：** D/DB/DP 的新增 payload 仅用于当前 v2 Rows 更新，遗漏字段须全为支持的 scalar 类型且无 extension；dataset 任意位置存在 blob，或遗漏 nested/List/Map/Dictionary 等字段时整组回到 early fill。full source、Columns、scalar-index 路径不能计算这项新增收益。[资格条件](ports/D/source/rust/lance/src/dataset/write/merge_insert.rs)
- **P 外围完整保留：** indexed 路径的未覆盖 fragments 也使用 scan budget，Union 改 Coalesce，join 从 Full 收窄为需要 source-only 时的 Left，否则 Inner；legacy/Columns sort 使用对应 MergeBudget。P/DP 本轮保留这些修改，Rows 非索引矩阵不验证其收益，也不能宣称 DP 已替代 indexed/Columns 策略。[indexed 外围](ports/P/source/rust/lance/src/dataset/write/merge_insert.rs)

## 6. 维护成本的量化

下表按统一基线文件字节与本轮 source 树，使用同一 `git diff --no-index --diff-algorithm=myers` 重新统计。`+/-` 包括注释和空行；Rust 文件在顶层 `#[cfg(test)] mod` 分开，`rust/*/tests` 与 Python tests 全计入测试。Python dataset.py 的变化经检查只有文档/doctest文本，单列而不冒充生产逻辑。它衡量需要审阅的文本面，不是复杂度或预计人天。原 patch 的 hunk 对齐算法不同会造成少量增删数差异，原始计数另存，不代表源代码不同。[可复算脚本](cost-audit.mjs)、[逐文件与 hash 记录](cost-audit.json)

| 版本 | 生产 Rust 增/删 | 生产 Rust 净增 | Python 文档增/删 | 测试增/删 | 修改文件数，仅作辅助 |
| --- | ---: | ---: | ---: | ---: | ---: |
| B | +128 / -46 | 82 | +7 / -5 | +193 / -36 | 3 |
| P | +165 / -46 | 119 | +18 / -25 | +454 / -129 | 5 |
| D | +532 / -129 | 403 | 0 / 0 | +988 / -58 | 3 |
| CTX | +33 / -8 | 25 | 0 / 0 | +156 / -0 | 1 |
| DB | +647 / -172 | 475 | +7 / -5 | +1178 / -90 | 5 |
| DP | +671 / -169 | 502 | +18 / -25 | +1424 / -186 | 7 |

D 的 condition 节点单独占生产 `+437/-96`，明显多于其 planner/context 接线。这部分维护对象是条件取值、候选行映射、缓存复用、nullable schema、分块状态、分区属性与错误释放。测试的大量新增主要覆盖这些边界，不能把生产改动与测试一起描述成“一千多行的新执行器”。

B 的持续维护对象是 source 前缀的顺序/完整性、EOF 与统计、空 schema、跨限整批、FirstSeen 去重后的统计、错误传播，以及 execute/uncommitted/analyze 入口一致性。P 的生产行数较少，但影响优化器选边与并行开关，并触及 indexed/legacy/Columns 外围；维护面比一个只改非索引 join 方向的补丁大。CTX 的对象最少，主要是 context 所有权和入口一致性。DB 要同时保持 source 缓存与 target snapshot/地址生命周期；DP 要保持固定选边、scan policy 和晚取值三者的语义组合，不能仅用代码净增估算风险。

上述代码量包含继承测试的修改和 P 新增的集成测试；测试源码存在不等于本轮已经运行或通过。通过数字、二进制身份和基准结果由主任务的本轮日志另行裁定。

## 7. 哪些组合可互补，哪些归因必须拆开

| 比较 | 能回答的机制问题 | 不能单独归因的部分 |
| --- | --- | --- |
| D 对 CTX | 在同样的共同 context 基础上，窄 target、晚取 payload、条件复用与软分块整体是否值得 | 不能拆出条件复用、chunk sizing 各自的独立收益 |
| DB 对 D | EOF source 准备及小 FirstSeen materialize 是否值得 | 没有实现原设计更严格的 source admission；source 准备带来启动屏障 |
| DB 对 B | late payload 与共同 pool 身份合在一起的变化 | 不能把全部差异只归给晚取列 |
| DP 对 P | 在同一固定 source-build / scan 设置下，晚取列及实际 analyze context 接线的变化 | P 的整表均宽 batch 策略可能同时限制 DP 的晚取 chunk 压力；需看真实计划/批粒度 |
| CTX 对 U | 项目 session factory 与实际 task context 统一的影响 | factory 包含 sort reservation、磁盘配置和函数注册，不是纯 pool 类型消融 |
| P 对 B | 固定 source build + 单路 probe + scan budget，对比 EOF 统计 + Auto 的整体取舍 | 不能把差异全解释为去掉 RoundRobin，也不能据总时间断言某个 scan API 更快 |

source 统计与 target 晚取列作用于不同成本，结构上可互补；固定 source build 与晚取 target payload 也可组合，但无法互相弥补 reverse 方向的容量不足。是否需要收益选择器、投影感知的 scan sizing 或 native scan，必须由本轮仍未解释的实际瓶颈决定；当前不把缺失机制写成已经解决，也不根据尚未完成的实验选出赢家。
