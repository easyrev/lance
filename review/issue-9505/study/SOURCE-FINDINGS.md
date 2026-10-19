# 源码判断：先验约束

以下为源码推导，运行证据另列。实验固定在 Lance 0a0d327 / DataFusion 54.1.0；当前 main 为 8c233c2，#10077 head 未变。main 的六个新提交没有修改本轮的 scan / join / Take / pool 边界，但包含版本、FSST、索引及 IO 改动；本轮不声称完成了新 main 的合入验证。

## 统计选边

DF 的默认 CollectLeft 阈值为 1 MiB / 131072 rows，比较是严格小于。存在 bytes 就只按 bytes 判断 collect，bytes 缺失才退到 rows；Exact 与 Inexact 都通过 get_value 参与。一般 swap 优先比较两侧 bytes，其次两侧 rows；缺一侧便保持初始方向。但 Auto 的 try_collect_left 有一个独立分支：某侧可 collect 而另一侧不可时，可直接选择前者，并不要求两侧统计可比较。只隐藏 bytes 还保留很小的 rows，仍能触发这个分支。源文件见 source/dependencies/datafusion-physical-optimizer-54.1.0/src/join_selection.rs。

#9430 不是 manifest 统计。它在 Lance io/exec/utils.rs 的 estimated_bytes_per_row / estimated_total_byte_size 中使用 schema 的固定宽度、decoder 的变量宽度种子与 Arrow offsets/validity；普通 Binary/Utf8 种子为 64 bytes，list 假设五项。materialized blob 返回 Absent；普通变长字段继续报告 Inexact。扫描、FilteredRead 与 Take 缓存或传播这项估计。压缩字节与解码值宽度不是同一量；全文件 bytes 也无法给 projected Arrow 值建立上界。新压缩 fixture 的两个旧 payload 解码后合计 256 MiB，而全部数据文件合计仅 41152 B；schema 和 manifest 两种策略、完整和未知 source 都实际选择 CollectLeft target，并在 64 MiB pool 下失败。详见 REPORT 的反例表。

B 的完整 EOF 输入能修复 source 缺少统计，但不修复 target 的错误宽度；不能保证两侧可比较时选对。DB 将遗漏 payload 从 target 投影移走，在 F16/Wn 的实际投影上避开部分宽度问题，但并不保护变长 key，也不改变 total target key/address/hash 随行数增长的事实。旧 C 的 StatsGuard 已做双 Absent，并从 source 默认方向开始，只有明确的小固定 target 例外。[C-r2 源码及匹配历史 freeze 的哈希](source/legacy-C/metadata.json)、[原单元日志和 W-auto 记录副本](inputs/legacy-C/)均保留，不在本轮重建 C；这些历史文件不计入本轮样本。

局部保护的可验证目标是：对实际投影含未知变长值的 merge target 撤回不可信 rows/bytes，同时选择 source-left 初始方向；固定宽小 target 仍让正常 Auto 规则换边。这是一项保守准入策略，不是估计更准确，更不证明任意 source 都能在内存中完成。仅做双 Absent 而保留 target-left，也会在两侧都未知时留下 Partitioned target build。

运行中 HashJoinInput 已在保留每个 incoming batch 和分配 hash map 前 try_grow，因此本轮错误是受控资源错误，旧 snapshot 全值保持不变。这不是严格解码内存保证：incoming batch 此时已经由上游解码，hashes/concat 等瞬时分配也不由输入 reservation 的峰值完整表达。最小的执行保护应保留在 build admission 的实际字节检查；希望资源不足后仍完成，还要有可重放输入和可 spill/改选边的 join fallback，单次 try_grow 不提供这些。要限制全进程峰值，还必须处理更上游的解码和单值大小；不能用一个更大的全局 pool 替代。

## 缓冲与并行

RepartitionExec 的输出 channel 在 send 时按完成 batch 的 get_array_memory_size 执行 try_grow；失败则走 spill，接收端取走 memory batch 时 shrink。SharedCoalescer 的未完成数组不经过该 reservation。Hash 分桶生成的 indices、take/copy 与上游已解码输入也不能全部从 channel reservation 推导。#26166 的这项观察成立。

RoundRobinBatch 按输入 batch 轮换，一个 batch 只交给一个输出 partition。SharedCoalescer 在它之后。LimitedBatchCoalescer 设置 biggest_coalesce_batch_size = session batch_size / 2；Arrow 对超过这个阈值的大 batch 在无残余缓冲时直接输出，保留整个 batch。session batch_size 是此处的合批目标，不是对已有输入的硬切分。因此即便设为 1，单个 25 行 / 250 MiB 的 batch 仍可能完整通过、交给一个分区并触发 spill。原始 Ws 不能据此归因为只有 SharedCoalescer 残余未记账；整批分发与 fair share 也是独立机制。

CollectLeft 的左侧 build 由 Arc<OnceAsync<JoinLeftData>> 在 probe partitions 间共享，不为每个 probe partition 复制完整 hash table；probe 输出、访问 bitmap、队列和解码窗口仍可增加。Partitioned 则每个分区独立 build 自己的数据。target_partitions 是优化器希望的并行度，不强制每条输入都产出那么多有效任务；repartition_joins 影响 join 物理分布与模式，enable_round_robin_repartition 允许 EnforceDistribution 在合格节点增加 RoundRobin。三者不能相互替代。

#26167 仍开放，head=3735590ff52c96a7b09b18cb3dc57825fee50345。该补丁显式使用 infallible grow 记录 coalescer capacity，能补可见性，但其作者也明确保留超额行为，没有实现压力下提前 flush；因此不能将“已记账”改述为“已受严格 pool 上限保护”。FairSpillPool 的 grow 无拒绝分支，try_grow 才执行限制；spillable 按份额、unspillable 按剩余总额检查。增加 output partitions 会改变这些份额与队列数量。

## #7363 与现有 D

#7363 的描述、2026-07-01 作者反馈与历史 commit 4a31cea63e232b93ac985949f9f66a78edf4f1f4 均已读取。作者已经指出 join/repartition 导致 Take 地址稀疏、低效，只有显著减少取值行数才值得。这个限制不会因把 D 的 condition 代码移动成一个物理 rule 而消失。

原 spike 的 rule 不等于当前提案覆盖的所有计划：它匹配 Projection -> HashJoin -> 左侧直接 FilteredRead，跳过 join filter，依赖列索引重映射，并仅处理其支持的 join 类型。正常物理优化可能插入交换、投影或交换 build/probe；这既缩小匹配范围，也构成 DF 升级的维护合同。只在 merge call site 应用能缩小其他查询的风险，但不能省掉内部 plan/schema/rowaddr 生命周期责任。

现有 TakeExec 确实与 D 产生不同执行路径：每个执行流缓存已打开的 FragmentReader，并允许多个 map_batch 并发；D 的每片 TakeBuilder 和逐分区串行软分块采用另一套生命周期。因此进行一个局部非空地址 spike 有意义，无需实现完整 rule。TakeExec 的可选 batch_size_bytes 在已经取值、merge 后才切输出，也不是读取前的硬分配限制。

现有 TakeExec 仍 debug_assert rowaddr 无 NULL，不能直接承接 source-only 行；#7363 的历史补丁专门增加 compact/scatter 和 nullable-extra schema。重复地址的 batch 内排序、去重、还原已存在。条件拒绝、delete/nothing 行及条件列复用，需要在 Take 点判断 action 并保留条件值；通用无条件 Take 不自动获得 D 的这些语义。CoalesceTake 只折叠相邻 Take（含允许的 CoalesceBatches 形态），不跨 join 选择列，也不把来自不同分区或不同批次的离散地址全局排序。

#7363 的宽度/storage gate 会排除本轮 N_dense 的 int64 遗漏列；这能避免该格回退，但属于启用范围的效果，可以独立用于专用实现。它把任意变长字段视为候选，仍不能从“变量宽度”推出“很宽或很稀疏”，也不能替代更新比例证据。

实际 spike 的三轮结果确认路径不同，却不支持直接替换：generic Take 在 N 阶段比原 D 更快，仍慢于 early；在 Wn 阶段比 D 更慢且 RSS 更高。因此停止整套 rule 的移植。本轮没有实现通用 Take 的 NULL/action 语义，也没有因此重新验证其完整 merge/retry 合同。
