# 源码假设验证与技术决策

本轮改变了对改进路径的判断，没有产生覆盖共同目标的新默认方案。manifest 字节修正和缩小 session batch_size 均被反例推翻，不能据此恢复全部自动选边与 repartition。现有 TakeExec 的实现确实改变成本，但既没有全面胜过 D，也没有消除 dense 相对 early 的回退。当前仍应与 #10077 合作拆解资源合同、选边和分布策略；late payload 维持范围受限的独立机制，不提交整包 DB 替代或完整 #7363 rule。

## 固定对象与证据等级

本轮基线保持 `0a0d327082988018a25f56147d3b6d02f6c79ecc`（U），DataFusion 54.1.0、Arrow 58.4.0。当前查询到的 main 为 `8c233c2e6aa6948524f352e5e4cd52bd1364f6ff`，比 U 多六个提交，未修改本轮 scan/join/Take/DF pool 边界。#10077 仍开放，head 为 `9e1ebc2e816a7195b56757ebe269e74989fc30c7`；#7363、DF #26166、其修复 PR #26167 仍开放。原始响应及 main diff 在 [inputs](inputs/)，不声称已验证新 main 的合入结果。

实际新二进制基于同 U 的 P 移植，加 test-only 私有研究驱动。它可恢复 Auto 的初始 target-left、插入局部统计策略、独立控制分布设置、执行真实 merge writer/commit 或明确标记的阶段探针。D 的 condition 产品代码以固定副本编译进私有测试模块，原生产路径未改成 D。unused CTX seed patch 在构建前已经撤销。完整差异、快照、二进制 SHA、Cargo compiler artifact、全树与 harness 哈希见 [freeze-v1](freeze-v1.json)；实际执行的是 ECS 上该冻结可执行文件，未把 Python 扩展目录名当实现身份。

下文“实测”指本轮已保存的执行计划、算子指标与独立完整字段 oracle；“源码推导”指上述固定源码；“历史实测”指已冻结的[统一实验](../unified-9505-20261019/README.md)，不计作本轮测量。完整源码解释见 [SOURCE-FINDINGS](SOURCE-FINDINGS.md)，架构责任见 [ARCHITECTURE](ARCHITECTURE.md)。

## 1. 先修正资源与选边合同

**实测：压缩文件大小不能可靠代表 projected Arrow build 大小。** 新 fixture 只有 128 行，LargeBinary 与 Utf8 各 1 MiB/行，两个旧 payload 解码后合计 268,435,456 B。四个数据文件合计 41,152 B，source 为 64 行、逻辑 525,312 B。source 分别通过完整 MemTable 和未知 reader 提供。manifest 策略使用全部文件 bytes 再加每行 16 B，而非按投影比例压低估计。

| 策略与输入 | 送入选边的 target rows / bytes | source rows / bytes | 实际 join / build | 结果与内存 |
|---|---|---|---|---|
| 当前 schema，complete | Exact(128) / Inexact(24,192) | Exact(64) / Inexact(1,576,800) | CollectLeft / target | 24 行已驻留，build 指标及 pool peak 50,332,932 B；追加约 16 MiB 失败 |
| manifest，complete | Exact(128) / Inexact(43,200) | 同上 | CollectLeft / target | 同样失败 |
| 当前 schema 或 manifest，reader | 与上相同 | Absent / Absent | CollectLeft / target | 同样失败，各自失败与 unchanged oracle 保留 |
| 局部 guard，complete / reader | Absent / Absent | 各自原值 | Partitioned / source | 均完成 64 次更新；build 指标 9,448,036 B，pool peak 约 9.01 MiB |

这里“完整”表示提供了已物化输入的统计，不表示 source bytes 是精确逻辑宽度：实际投影报 Inexact(1,576,800)，应读取原统计，不能用逻辑 512 KiB 替换后推导 CollectLeft。失败发生在 64 MiB FairSpillPool；四个失败样本 RSS 约 314–324 MiB，原 snapshot、全部字段与版本未变。两个成功 guard 样本 RSS 约 649–668 MiB，交换累计 spill 各约 256 MiB、临时文件峰值约 32 MiB。完成更多 scan/write 的成功进程峰值反而更高；不能宣称 guard 封顶 RSS。

**源码推导：** DF Auto 的 collect 阈值是严格 `<1 MiB`，只有 bytes 缺失才 fallback 到 `<131072 rows`；Inexact 也参与比较。一侧可 collect、另一侧不可时，可单边选择，不要求两侧都能比较。一般 swap 优先比较两侧 bytes，再两侧 rows。source 缺失且 target 超过 collect 阈值时，保留初始方向的分支仍存在。已确定的 CollectLeft 不重新按阈值决定模式，Partitioned 也不自动变成 spillable hash join。#9430 使用 schema/decoder 种子估计变量宽度，普通 Utf8/Binary 种子为 64 B，并未引入 manifest 统计。固定宽度可以提供有用估计，压缩大小与变量宽度不能提供严格解码上界。

**实测：可以局部限制危险选择，同时保留一部分合法 swap，但目前不是完整 reverse 解法。** guard 对实际 target 投影中的普通变长字段撤回 rows 与 bytes，并把初始 build 放 source；固定宽度 target 继续参加正常 Auto。1000 行固定宽 target / 5000 行 source 的 complete 和 reader 都自动换为 CollectLeft target，build 指标 20,000 B，pool peak 分别 267,216 / 385,736 B；全值验证更新 1000、插入 4000。仅 mask 而保持 target-left 的计划仍为 Partitioned target build。原始 100 万行 target / 300 万行未知 reader 的 guard **只检查计划**：target key/address 为固定宽且估计 24,375,000 B，不可 collect；source 未知，最后仍为 Partitioned source build。该计划不证明新的资源失败，但足以否定“本 guard 已解决原 reverse”的主张，无需重复旧 P 的容量失败。

B 的 EOF source 统计已经解决一部分缺失来源信息的问题；DB 叠加窄 target 投影，在 F16/F64 有历史实测收益。两者都不修复任意变长 target 的宽度错误，也不限制 hash 状态增长。旧 C 的双 Absent + source 初始方向已覆盖本次 guard 的关键思想，避免把同一机制作为新发明再叠一层。新 guard 也只识别本反例的直接 Binary/Utf8 类型，未实现可交付的递归类型与 blob 准入规则。

**工程决定：** 停止 manifest-as-Arrow 的生产移植；保留有明确来源的 source 统计、同 attempt 的共同执行 context，讨论 merge 局部的统计可信度与初始方向保护，不全局宣称必须关闭 DF join_reordering。撤回 target 统计是准入保护，不是更准确的估计。原始大 reverse 仍需要可信的两侧规模、可回放/可落盘输入或执行时 fallback，当前 spike 未实现这些。

HashJoinInput 在保留 incoming batch、分配 hash map 前已有 `try_grow`，应保持这个最小 fail-fast 边界。估计无论多好，都不能替代按实际保留字节准入。它收到的 batch 已经解码，concat/hash scratch 等瞬时分配也没有因此成为硬界；若要保证超限后仍完成，需要 spillable/adaptive join 与重放合同，若要限制进程峰值还要处理上游解码与超大单值。扩大全局 pool 不解决这两个不同要求。

## 2. 分发粒度与缓冲记账必须分别处理

**Opus 对未记账 coalescer 的发现成立，对其解释范围推得过远。** DF 54.1 的 Repartition channel 对完成 batch 执行 `try_grow`，失败 spill，接收后 shrink；SharedCoalescer 尚未完成的数组没有同样记账。分桶 indices、copy/take 和上游解码又有各自瞬时成本。DF #26167 补丁使用分配后的 infallible `grow` 记录 coalescer，作者明确保留超额可能；它提高可见性，不提供压力下提前 flush 或硬上限。

RoundRobinBatch 按整批轮换，合批发生在分发之后；大 batch 可绕过 LimitedBatchCoalescer 的小批合并路径。session batch_size 不是输入拆分器。CollectLeft 的 hash build 在 probe partitions 间由 OnceAsync 共享；增加 probe partitions 不复制完整 hash table，但仍增加 probe/队列等成本。repartition_joins、enable_round_robin_repartition、target_partitions 作用不同，不能仅看配置推测实际 join mode。

实测直接 RoundRobin 阶段，固定 Ws 同一组 25 行 / 250 MiB source 值、16 个输出、1 GiB pool：

| 输入与配置 | 实际有数据分区 / 16 | 输出批 | 累计 spill | 单次诊断 wall / CPU | 说明 |
|---|---:|---:|---:|---|---|
| 单批，batch_size=8192 | 1 | 1 | 262,144,824 B | 1.088 / 0.87 s | 唯一大批完整交给一个输出 |
| 单批，batch_size=1 | 1 | 1 | 同上 | 1.064 / 0.88 s | 缩小配置没有拆批 |
| 同值 25 批，8192 | 16 | 16 | 0 | 0.306 / 0.39 s | 每分区 1–2 行 |
| 同值 25 批，1 | 16 | 25 | 0 | 0.143 / 0.25 s | 每分区 1–2 行 |
| 单批，1，交换前逻辑 16 MiB 拆分并紧凑复制 | 16 | 25 | 0 | 0.293 / 0.38 s | 实际每片约 10 MiB，一行新值已有 10 MiB |

最后一项是支持的字段类型上的最小原型：按实际行值长度拆分，Arrow take 紧凑复制，再交给真实 RepartitionExec。它同时改变批次粒度和 backing-buffer 生命周期，因此不能把全部收益归因于 CPU 并行。输入大批仍先被解码，一行大于目标时仍会过冲，不是通用 byte admission。三轮配对的数值见下一节与原始记录。无 spill 的 prototype reservation 高于原单批的 0：原单批因 try_grow 失败直接落盘，0 reservation 绝不表示没有内存。

完整 Rows merge 对 Ws 单批与同值多批分别执行 P 保守策略、恢复 join/RR 分布、恢复后 batch_size=1。保守策略是 CollectLeft source、无交换；恢复两项设置后实际是 Partitioned source、两侧 Hash(16)，**这组完整 merge 并不包含 RoundRobin**。两种输入形式均正确；原批大小恢复配置的诊断 wall 为 7.98 / 7.51 s，RSS 约 5.01 / 4.97 GiB，target 交换累计 spill 约 2 GiB。batch_size=1 降低合批滞留和 spill，但仍有 target spill 约 430 MiB；单批 source 还 spill 约 250 MiB。保守策略均无交换 spill。它们同时改变 mode、交换和输出批大小，不能仅归因于 SharedCoalescer。

**工程决定：** 不用小 session batch_size 或更多分区作为恢复全部 repartition 的依据，不以配置分区数宣称有效并行度。本轮没有 CPU 并发时间线，不能把 16 个活跃输出写成 16 倍执行并行。最小的缓冲修复应在 copy/合批前按 capacity 差额尝试 reservation，压力下 flush 已有批并让完成批进入受限 channel/spill；超大输入则必须在 exchange 前处理粒度或明确拒绝/旁路策略。通用 DF 行为适合在 #26166/#26167 协作，Lance 控制扫描投影、解码窗口与 merge 入口。旧 C 的 native target scan 不会拆开 source 的大批，本轮没有为此重建 C。

按 pool 降低 target_partitions 可能减少队列/活跃 consumer 并改变 fair share，是可用的资源取舍；它既不能把一个 RoundRobin 输入批分给多个 worker，也不能约束未知单值的大小。本轮保持 16 以隔离已有建议，没有实现或否定某个具体自适应 P 算法；当前证据只足以否定“按行减小 batch 已解决宽批成本”。若有人提出具体 P 策略，应先用同一失败机制做一个针对性检查，无须先展开并行矩阵。

## 3. #7363 提供复用机会，没有自动消除 late 的代价

现有 TakeExec 有执行流内 FragmentReader cache 与 map_batch 并发；D 的 condition 为串行软分片，每片构造 TakeBuilder。这是足以进行 spike 的实际差异。两者都在 join 之后按离散地址取旧列，仍有页覆盖、排序/散射、重复 batch 取值与新增数组成本。TakeExec 的 batch_size_bytes 在完整 fetch/merge 后才切输出，不能保护读取峰值。CoalesceTake 只折叠相邻 Take，不跨 join 决策，也不全局合并不同批次地址。scanner late materialization 能复用宽度/storage gate，无法自行知道 join/action 的存活行。

本轮只手工构造同一真实 join 后的 early / D condition / generic Take 三种节点形态，UpdateAll、非空地址，无 writer/commit，使用共同 IPC sink 并独立逐字段验证。Wn 为 sparse wide，N_dense 为窄整数 90% 更新；实际 join 在各自对照内保持一致。它不是完整 #7363 规则或最终 merge 产品实现。配对结果见下节。

既有 Take 的 batch 内重复地址排序/去重/顺序恢复测试通过，不代表重复 source key 的 merge 政策由 Take 负责。当前通用 Take 仍断言 rowaddr 无 NULL，不能直接承接 source-only 行；#7363 历史补丁需要 compact/scatter 与 nullable-extra schema。条件更新还要避免读取被拒绝、delete/nothing 行的 payload，复用已读条件列，保留 writer 原 rowaddr；放在条件之前或之后都不能省掉 action 合同。错误会随 stream 传播，但 snapshot 改变后的 retry 必须重建匹配与地址，不能复用旧执行流的 reader/plan。上述扩展属于源码分析，未在 generic spike 实现或声称通过完整 retry 测试。

历史 #7363 rule 匹配 Projection -> HashJoin -> 左侧直接 FilteredRead，跳过 join filter，还需重映射列与物理属性。source-build 方向、右侧 target、Repartition 或投影插层会改变匹配；只在 merge_insert 启用可缩小其他查询风险，不能免除 DF 升级、with_new_children、schema/rowaddr 契约。原宽度 gate 会排除 N 的 int64，因而可避开这格回退；收益选择范围可以独立用于专用节点，不能归功于 generic rule。任意 Utf8/Binary 入选仍会遇到 dense variable 成本，旧 V 已提供反例边界。

**工程决定：** 停止完整 rule 移植和直接以 TakeExec 替换 D。可以向 #7363 提供非空阶段证据、NULL/action 契约清单，讨论复用读取内核；目前没有证明它以更低总维护成本达到 D 的宽字段收益并避开 dense 回退。D 约 403 行净增的旧产品代码不能与一个研究调用点的十几行直接比较，rule 还包含跨节点重写和通用 Take 新语义的责任。

## 4. 三轮配对与可信边界

配对种子、每轮组/配置随机顺序、运行前身份复查见 [paired-plan](paired-plan.json)、[paired-freeze](paired-freeze.json)。所有格独立进程、相同 8 GiB cgroup / swap=0、同 ECS、相同支持的实际 FairSpillPool。ObservedPool 串行记录 reservation 变动，所有新配置共用；其仪表开销与 IPC 输入合同意味着本轮时间不能与旧 Python API 时间混合计算。完整 merge 计时包括 execute+commit，不含规划或 complete 输入预物化；阶段计时包括执行+共同 IPC sink。全部为明确预热的本地文件；不推断冷读、对象存储或通用 CPU 扩展性。

本节最终数值由 results.json / results.md 及 audit-final.json 固定，诊断样本不混入三轮比率。比率使用同 block 的 numerator/denominator 再取三轮中位数；失败和 plan-only 不参加计时排名。CPU、RSS、pool、IO、TMP、每分区和每节点指标均保留在原记录。

| 比较范围 | 三轮各自 wall 中位数 | 同 block 时间比中位数（范围） | 决策含义 |
|---|---|---|---|
| Ws 完整 merge：恢复分布+batch=1 / P 保守策略 | 3.145 / 2.378 s | 1.338（1.289–1.355） | 小 batch 没有恢复完整链路优势 |
| Ws RoundRobin 阶段：拆分复制 / 仅 batch=1 | 0.297 / 1.077 s | 0.276（0.259–0.284） | 粒度/backing 改变确实影响本阶段，不外推完整 merge |
| Wn 阶段：generic Take / D condition | 0.370 / 0.162 s | 2.276（2.198–2.335） | sparse wide 不支持直接替换 |
| N 阶段：generic Take / early | 0.0715 / 0.0368 s | 1.941（1.940–2.268） | 仍有 dense 回退，绝对差约 35 ms |
| N 阶段：D condition / early | 0.240 / 0.0368 s | 6.552（6.419–6.579） | 原 D 路径代价更高 |
| N 阶段：generic Take / D condition | 0.0715 / 0.240 s | 0.302（0.295–0.346） | reader cache/并发路径值得区分，未成为综合赢家 |

| 成功配对配置 | CPU 中位数 s | tracked pool peak 中位数 MiB | sampled RSS 中位数 MiB | 执行 rchar 中位数 B |
|---|---:|---:|---:|---:|
| Ws P | 4.41 | 250.00 | 2848.74 | 2,359,459,649 |
| Ws 恢复分布+batch=1 | 5.58 | 490.02 | 2778.15 | 2,621,610,673 |
| RR 仅 batch=1 | 0.85 | 0 | 563.70 | 524,290,090 |
| RR 预拆分复制 | 0.39 | 100.00 | 454.53 | 262,145,274 |
| Wn D condition | 0.17 | 0.197 | 186.81 | 131,234,886 |
| Wn generic Take | 0.45 | 0.197 | 595.86 | 131,236,039 |
| N early | 0.05 | 22.03 | 134.69 | 9,932,427 |
| N D condition | 0.33 | 13.51 | 211.03 | 169,411,538 |
| N generic Take | 0.45 | 13.09 | 258.33 | 169,368,440 |

generic N 较低 wall 同时带来较高 CPU 与 RSS，不能只写“优化了 dense”。两个 late N 的逻辑读取均约 169 MB，而 early 约 9.93 MB；在不同节点中使用相同离散 join 地址，没有消除重复取页工作。这里只证明进程读取工作量差异，不精确归因每一页的重复次数。所有正式配对的 read_bytes 为 0，不能用 rchar 宣称物理盘读取。完整 Ws 的 write_bytes 中位数 P 为 393,314,304 B，恢复分布+小批为 1,106,464,768 B；TMP 峰值分别 0 与 450,937,568 B，累计 exchange spill 后者约 713 MB。最终新行内容相同，累计执行写入、累计 spill 和临时文件峰值不应混为一项。

Arrow get_array_memory_size 是本次 channel 的实际记账依据，但 IPC-backed 列可能共享大 backing，跨数组求和可重复计数，不能当唯一物理 RAM。RSS 与 cgroup 对共享/文件页的归属也不同。ObservedPool 高水位只精确反映被登记的 reservation，未登记空间不能通过 RSS 减 reservation 精确推算。53 格记录、60 项既有定向单测与最终审计的口径见 [VALIDATION](VALIDATION.md)。

## 5. 最小可靠设计与贡献路径

按工程影响排序：

1. **先修资源合同与选边证据。** 保留同 attempt 的规划/执行 context 和实际 pool、可靠的已有 provider/EOF 统计与 retry 错误传播。不要以 compressed bytes 充当解码准入，不把固定 source-build 扩成所有负载默认。局部可信度屏障值得在 #10077 中讨论，但本 guard 不是完整替代方案；尤其原 reverse 计划仍是反例。已有 B/C 解决的部分应合并语义，避免叠加重复准备器或统计 wrapper。
2. **暂不凭 batch_size 恢复所有分布优化。** 对已观察到的宽批链路保留保守执行选项；要恢复交换，先解决字节粒度、缓冲记账/提前 flush 和超大单值策略。不能把两项配置都关掉的 P 测量，外推为其中任意单项的独立收益。DF 的通用 coalescer/exchange 修复与 Lance 的 scan/source 合同分开承担。
3. **early 作为普通窄列的基线，late 收窄范围。** DB 的 F16/F64 与 Wn/Ws 容量收益仍成立；dense narrow 和 V 的 CPU 取舍也继续成立。保留 D 的条件列复用、action-aware 补值和 snapshot 边界，作为明确适用 sparse/wide 负载的候选。不能以“变长”或“source 行少”单独决定启用；本轮没有构建可信的全自动覆盖率选择器。
4. **不追加完整 generic rule、native scan 或自适应 join。** 当前关键假设已被否定，不为维持某项实现继续加机制。Take 的读取复用可以后续单独评估，不能以理论通用性先增加跨模块责任。#10077 的 indexed/Columns 外围继续由原工作承担，本轮不宣称全面替代。

这是一条可执行的最小修复路径，**尚未形成覆盖所有共同目标的默认产品实现**。对规模/宽度未知的任意 reader，受限 pool 的受控失败与业务总能完成是两种承诺；当前只有前者的局部证据，没有后者。DB 仍是历史已验证的有价值组合，当前信息不足以将其设为全局默认，也没有证据表明增加本轮任一机制就成为“killer”。

下一项最有价值的 Lance 贡献是参与 #10077，提供压缩 target 的 complete/reader 反例、source-left 与双统计撤回的局部替代及其 reverse 边界，并把共同 context 的确定性修正与策略选择拆开审查。DF 方面优先把单超大批与多批、reservation/spill/实际输出分布的可复现测试反馈到已有 #26166/#26167，讨论 byte-aware pre-flush；不另开重复修复。#7363 先提供本轮阶段证据和 NULL/action 缺口，不建议立即新建通用优化 PR。当前应先交付补丁与证据并协作，未达到推荐独立整包性能 PR 的门槛；本轮没有实际发布任何评论或 PR。

本轮无需再扩矩阵。会改变决策的后续验证只有：一个具体局部选择策略能否同时通过压缩 target 与原 reverse；或 DF 的具体 byte-aware 修复能否在相同完整 merge 中消除资源/时间损失。仅继续调 batch_size、增加分区或移植完整 rule 不会回答尚缺的决策证据。
