# 实际计划诊断

本文件记录已落地的 analyze 文本及独立 execute 结果，不运行新工作负载。analyze helper 会丢弃 stream Err，因此 `validated_diagnostic`、计划文本存在或 writer counters 达到预期，都不单独证明完整执行。以下机制判断来自已观察的物理树；完成性来自对应的独立 execute 与 oracle。analyze 的时间不进入性能配对统计。

## F16：窄 target 扫描与小 source build 是两项不同的改进

已读取 `diagnostics/diagnose-f16-v1-F16-{B,P,D,DB,DP}-rewrite_rows-b0/analyzed-plan.txt`，五份均没有解析遗漏，HashJoin 均为 Inner、两个输入子树完整。机器提取存于 `diagnostic-f16-extraction.json`，保留原始字符串、节点/行号与文件 SHA256。独立 `runs/pairs-f16-v1-F16-{B,P,D,DB,DP}-rewrite_rows-b{1,2,3}/result.json` 共 15 份全部为 `validated_success`。后续同步已补齐 DP result：五份诊断均为 `validated_diagnostic`、`atomicity_validated=true`，文本 hash 与 metrics 相符；诊断状态仍不替代独立 execute 完成证据。

### build/probe 与扫描的实际差异

表中 `K/M/B` 保留原文，是十进制 generic metric 缩写：`4.70 K` 约 4700 bytes，`957.4 M` 约 957,400,000 bytes；这些是汇总的 build 指标，不是进程 RSS。target 均为本格 dataset 的 LanceRead；source 在上游 Projection 中带 id/c0/c1 与 source sentinel，可与 target URI 区分。

| 候选 | HashJoin mode | build 来源 / 行数 / build_mem_used | probe 来源 / 行数 | Repartition | target 投影（另含 row_id/row_addr） | target bytes_read |
|---|---|---|---|---|---|---|
| B | CollectLeft | source DataSourceExec；100；4.70 K | target；16.00 M | target probe：RoundRobinBatch(16) | id、c2…c42 | 3.35 B |
| P | CollectLeft | source StreamingTableExec；100；4.70 K | target；16.00 M | 无 | id、c2…c42 | 3.35 B |
| D | Partitioned | target；16.00 M；957.4 M | source StreamingTableExec；100 | build 与 probe 均 Hash([id],16) | id | 47.05 M |
| DB | CollectLeft | source DataSourceExec；100；4.70 K | target；16.00 M | target probe：RoundRobinBatch(16) | id | 47.05 M |
| DP | CollectLeft | source StreamingTableExec；100；4.70 K | target；16.00 M | 无 | id | 47.05 M |

五个 target scan 都输出/扫描 `16.00 M` 行、160 个 fragments，`row_id=true,row_addr=true`，`full_filter=--,refine_filter=--`。这里减少的是每行读取的字段，**没有观察到 target 扫描行数减少**。B/P 的 scan I/O 为 `iops=9.28 K, requests=960`；D/DB/DP 为 `iops=640, requests=640`。三个 late 候选的相同 scan bytes_read 只覆盖 LanceRead；内部 payload Take 的存储读取没有包含在该叶子指标中，不能拿 `47.05 M` 当作整个 merge 的读取量。

实际边界可由原始文本定位：B 的 HashJoin 在第 4 行、RoundRobin 在第 7 行、scan 在第 8 行；P 的 HashJoin 在第 3 行、scan 第 7 行；D 的 HashJoin 在第 5 行、两个 Hash Repartition 在第 6/8 行、scan 第 7 行；DB 的 HashJoin 在第 5 行、RoundRobin 第 8 行、scan 第 9 行；DP 的 HashJoin 在第 4 行、scan 第 8 行。所有出现的 Repartition 都报告 `spill_count=0,spilled_bytes=0,spilled_rows=0`；P/DP 树中没有 Repartition/Sort。这是这次诊断中这些节点的观测，不能替代整个真实 execute 的所有临时文件审计。

### late 与 writer 计数

| 候选 | HashJoin 输出行 / batch | payload_take_rows | payload_take_arrow_bytes | condition Take / reuse | writer 更新 / 插入 / 删除 |
|---|---|---:|---|---|---|
| B | 100 / 16 | 无 late 节点 | 不适用 | 不适用 | 100 / 0 / 0 |
| P | 100 / 1 | 无 late 节点 | 不适用 | 不适用 | 100 / 0 / 0 |
| D | 100 / 16 | 100 | 95.78 K | rows=0、bytes=0、reuse=0 | 100 / 0 / 0 |
| DB | 100 / 16 | 100 | 95.78 K | rows=0、bytes=0、reuse=0 | 100 / 0 / 0 |
| DP | 100 / 1 | 100 | 36.74 K | rows=0、bytes=0、reuse=0 | 100 / 0 / 0 |

D/DB 的 MergeCondition 在第 3 行，DP 在第 2 行；均为 `take=[]`、`payload=[c2,…,c42]`，输出 100 行。五个 writer 均在第 1 行，报告 1 个文件、`bytes_written=44.78 K`。这些计数与 fixture 目标一致，独立 execute 的成功记录支持业务结果已经完成；writer 本身 `output_rows=0` 是其不输出数据批次的行为，不能解释成没有写入。

DP 的 `payload_take_arrow_bytes=36.74 K` 小于 D/DB 的 `95.78 K`，但三个候选都只取 100 行、相同 41 个字段。这个 counter 累加每次返回数组的 `get_array_memory_size()`，会受分批、capacity、backing buffer 和数组元数据影响（`ports/D/source/rust/lance/src/dataset/write/merge_insert/exec/condition.rs:482–499`）。不能据此认定 DP 少读了约 59 KB 的存储数据或少取了逻辑值。类似地 HashJoin 的 output_bytes 为 B=46.0 MB、P=2.9 MB、D/DB=5.0 MB、DP=320.1 KB，即使输出行都是 100，也不能当作逻辑 payload 大小或唯一分配峰值。

### 本次可以更新哪些解释

**已证实的计划机制：** D 的 target build 保留了 1600 万行，DB 的 build 切到 100 行 source；原先“F16 的 D/DB RSS 差异可能由 build 侧改变引起”的假设得到实际计划支持。同时 D/DB 的 scan 行数、投影、bytes_read 与 payload_take_rows 相同，不能把两者差异解释为 DB 又少扫描了一批旧 payload。D 的 `build_time=1.61s` 是跨 partition 汇总，DB 的 `110.52µs` 属于小 source build；两者支持 build 工作量不同，但不能相减后称作 wall-time 收益。

**已证实的互补性，仅限本格：** B/P 都用小 source build，却仍提前扫描 41 个遗漏列；D 仅做窄扫描，仍保留大 target build；DB/DP 在 F16 同时具备窄扫描和小 build。这解释了为何“只缩列”与“只改变 build”各自仍留有明显工作量。尚未证明任何选边策略能在大 source、反向大小关系、密集更新或未知统计输入上同时成立，不能用 F16 为固定 source build 或默认 late 作全面背书。

**DB/DP 之间尚不能单独归因的部分：** 两者 build 行数/内存相同，scan 与 Take 行数相同；DB 的 target 经过 RoundRobin(16)，join 输出 16 个 batch；DP 没有这条交换边，join 输出 1 个 batch。三个候选使用相同的 late 实现，但其输入 partition 数、分批和可并行 Take 不同。DP 的普通非索引路径调用 `MergeBudget::new(&self.dataset,None)`（`ports/DP/source/rust/lance/src/dataset/write/merge_insert.rs:2717`），**没有把 session.target_partitions 设置为 1**；没有 Repartition 与整个 session 只有一个 partition 是不同事实。scan 解码任务仍可以并行。仅凭这些计划与单次 analyze，不能把 DB/DP 的时间差只归到交换、批量或某一个 Take 行为。

后续 Ws/N/V 沿用同一判断尺度：先确认实际的 build 侧及 spill 节点，再比较 scan/Take 工作量与独立 execute 配对；若文本缺失实际 batch 配置、Take 调用数或存储读取，不从 Arrow bytes 倒推。

### 原始文本身份

以下均位于 `diagnostics/diagnose-f16-v1-F16-<variant>-rewrite_rows-b0/analyzed-plan.txt`；五个文本 SHA256 均与各自 metrics.json 的 analyzed_plan_sha256 相符。

| 候选 | SHA256 |
|---|---|
| B | `1cd0b4c8c63651f543e3c2bd454d732b62f8e31ad472571e5f1081cb3f10db83` |
| P | `61100f9578e35890c1b0baf3f840c5150657b3d45a880d64365fc109a0bacc8e` |
| D | `ad21109a91cbb56ba224d9a077ba6a2e336ab84cca7fac9b52bc260d27fb0e21` |
| DB | `c42ac2e10a776aaba0c46ecb09992fef997ddd456737698e41d9b1f80cab737a` |
| DP | `0ca6b60d412ff1b6bbc07942a969c75011362aacaa94e5ae7e88904d3215ace4` |

## Ws：source probe 的整批交换产生 spill，DP 同时改变选边与交换

已读取 `diagnostics/diagnose-ws-v1-Ws-{P,D,DB,DP}-rewrite_rows-b0/`，四份 result 均为 `validated_diagnostic`、`atomicity_validated=true`，四份 plan SHA256 与 metrics 相符。机器提取存于 `diagnostic-ws-extraction.json`。独立 `runs/pairs-ws-v1-Ws-{P,D,DB,DP}-rewrite_rows-b{1,2,3}/result.json` 共 12 份全部为 `validated_success`。下面的算子指标只说明本次诊断中观察到的机制，不把 analyze wall time 加入 execute 配对。

### 实际 build/probe 与 spill

| 候选 | HashJoin mode | build 来源 / 行数 / build_mem_used | probe 来源 / 行数 / 输入 batch | source 交换 | target scan 投影 / bytes_read |
|---|---|---|---|---|---|
| P | CollectLeft | source；25；262.1 M | target；400；144 | 无 | id、c0、c1、payload、row_marker / 2.10 B |
| D | CollectLeft | target；400；8.00 K | source；25；1 | RoundRobinBatch(16)，spill 1 次、25 行、250.0 MB | id / 70.82 K |
| DB | CollectLeft | target；400；8.00 K | source；25；1 | RoundRobinBatch(16)，spill 1 次、25 行、250.0 MB | id / 70.82 K |
| DP | CollectLeft | source；25；262.1 M | target；400；144 | 无 | id / 70.82 K |

四份 source 都是 `StreamingTableExec: projection=[id,new_payload]`；producer 记录各 1 batch、25 rows、262,144,400 Arrow bytes。D/DB 计划的第 7 行直接把 spill 归属到 source probe 的 Repartition，输入来自第 8 行 source Projection 和第 9 行 StreamingTableExec，随后进入第 5 行 HashJoin。该 Repartition 的 `output_rows=25,output_batches=1,spill_count=1,spilled_rows=25,spilled_bytes=250.0 MB`。P/DP 的树中没有 Repartition 或 Sort。原先“约 250 MiB 临时文件可能来自 source 交换”的解释，现在有同配置诊断的逐算子证据；原始 execute 未记录逐算子指标，不能声称已恢复其每一次 I/O 的时间与调用栈。

**16 个输出 partition 没有在本格制造 16 路有效 probe 并行。** DF 54.1 的 RoundRobin 分支把 `next_idx` 加一后，返回仅含 `(idx,batch)` 的单元素迭代器，保留整批，不按行拆分（本地 `datafusion-physical-plan/src/repartition/mod.rs:783–791`；[可移植源码摘录](dependency-excerpts/round-robin.md)）。这里唯一一个 250 MiB source batch 只进入一条输出边，实际指标也只记录 1 个输出 batch。在这批输入上，交换产生了 spill，却没有把这一个大 batch 均分给 16 路 probe。不能据此推论多 batch source 或其他 repartition 类型也无并行收益。

四份 target scan 都是 400 行、16 个 fragments，带 row_id/row_addr，无 target filter。D/DB 的 target build 接收 16 个 batch；P/DP 的 target probe 接收 144 个 batch。这是实际批数差异，和 P 按整表平均宽度缩小 scan batch 的代码相容；仅凭汇总文本还不能还原每批行数分布。DP 即使只扫描 id，也仍采用全表平均宽度 sizing；普通非索引路径的 `MergeBudget::new(dataset,None)` 不把 session.target_partitions 改为 1。

### late、writer 与内存口径

D/DB/DP 的 MergeCondition 分别在第 3/3/2 行，均为 `take=[] payload=[c0,c1,payload,row_marker]`：`payload_take_rows=25`、`payload_take_arrow_bytes=262.2 M`，condition rows/bytes/reuse 都为 0，输出 25 行。三个 late 候选的 scan 指标完全相同：`bytes_read=70.82 K,iops=64,requests=64`；P 的宽 scan 为 `bytes_read=2.10 B,iops=332,requests=152`。内部 Take 的存储 I/O 未被这些 scan 叶子指标覆盖。

四份 writer 都在第 1 行，更新/插入/删除为 `25/0/0`，1 个文件、`bytes_written=393.2 M`。这与独立 execute 验证结果一致。旧 payload 的逻辑值为 25×5 MiB，但 Take 的 Arrow counter 约为 262.2 million bytes；该差异本身说明不能把数组内存记账当作精确旧 payload 存储读取量。D/DB 的 CoalescePartitions 还记录 `output_batches=25,output_bytes=6.2 GB`：逐个输出切片可重复保留同一 250 MiB source backing，累加 get_array_memory_size 可能重复计入这份 backing。它不能证明发生了 6.2 GiB 的唯一内存分配、memcpy 或结果写入。

### 机制解释的更新与仍未分离的成本

**已证实：** D/DB 在 Ws 选择了极小的 target build（8.00 K），DP/P 选择了大得多的 source build（262.1 M，约 250 MiB）。因此即使 DP 的独立 execute 配对表现更好，也不能解释为 DP 保留了更小的匹配表。DP 同时避免 source RoundRobin spill，并把 target 放到 probe，改变 scan 批次和下游执行形态；具体时间贡献没有分别消融。D/DB 的 source 仍为 StreamingTableExec，与 B 预读在 250 MiB 单批越过 100 MiB 上限后不再轮询 EOF 的路径一致；这次 DB 没有重现 F16 的小 source MemTable 选边变化。

**对下一步设计的约束：** build 侧的保留字节、交换是否需要发生、以及输入批次能够产生多少有效并行，应分别评估。Ws 证明“小 build + 默认交换”仍可能引入不必要的临时 I/O，而“较大 build + 无交换”也可能在此输入上成立；它没有证明应无条件固定 source build。后续若将选边与交换策略解耦，需要对 source 更大、batch 更多和 target 更大的反例重新验证。当前证据不等于验证了任何具体 selector 或 native scan 方案，也不把 DP 的全部差异归给单一交换开关。

### Ws 原始文本身份

以下均位于 `diagnostics/diagnose-ws-v1-Ws-<variant>-rewrite_rows-b0/analyzed-plan.txt`。

| 候选 | SHA256 |
|---|---|
| P | `8d294264f1738673a4e719e5086e49e92f848a3ff5f15292ad48342398d22877` |
| D | `379713e656852218800bcad609e175e2593ec116f7460759bd8ce98f8ace8fdb` |
| DB | `986a96870082565646881385e7848b4f9b231bdbb92a812c364b2987aa7b3851` |
| DP | `028545f189b656ef026c25234aab3a2572d7466ce8252dff868a1d5f9fa41e8c` |

## Wn：较小 build 与更多 scan batch 并存，没有 spill 差异

`diagnose-wn-v1-Wn-{D,DP}-rewrite_rows-b0` 两份诊断均为 `validated_diagnostic`、原子验证为真，文本 hash 与 metrics 匹配；本次没有 Wn/DB 诊断计划。D/DP 的独立三轮 execute 共 6 格均为 `validated_success`；DB 的独立三轮也成功，仅用于下面的结果对照，不替它补造物理计划。

| 指标 | Wn/D | Wn/DP |
|---|---|---|
| HashJoin | CollectLeft，target 400 行 build / source 25 行 probe | CollectLeft，source 25 行 build / target 400 行 probe |
| build_mem_used / 输入 batch | 8.00 K / 16 | 2.26 K / 1 |
| target scan 到 join 的 batch 数 | 16 | 144 |
| source exchange | RoundRobinBatch(16)，输出 1 batch，spill=0 | 无 exchange |
| scan 投影 / 行数 / bytes_read | id + row_id/row_addr；400；70.82 K | 相同 |
| HashJoin 输出 | 25 行，1 batch | 相同 |
| late Take | 25 行，262.2 M Arrow bytes | 相同 |
| writer | 更新 25、插入/删除 0；1 文件，131.1 M bytes_written | 相同 |

D 的 source 只有 1 个 600-byte batch，RR16 按整批分配，不能把这 25 行的下游 Take 描述成 16 路实际并行；这与 Ws 的有效并行约束相同，但没有宽 batch 的 spill。DP 的更小 build 也不能单独解释时间：三轮 execute 的 wall 中位数为 D=0.242s、DB=0.248s、DP=0.344s，CPU 中位数为 0.415s、0.418s、0.361s；三者没有采样 TMP，rchar 约 131.23 MB，最终数据文件均 131,079,501 bytes。DP CPU 更少而 wall 更长，因此现有证据不支持“DP 多读了 payload”或“D 有 16 路有效 Take 并行”。

DP 的 144 个 target probe batch 与全表均宽 sizing 的小批次相容；选边、scan 分批、交换配置和消费背压同时变化，尚未分离各自对 wall 的贡献。叶子 `elapsed` 也可能包括下游消费间隔，不应视为独立 scan CPU。D 的 Coalesce 观察到 25 个 late 输出 batch；DP 没有对应 Coalesce，MergeCondition 的 output_batches 未记账，不能凭默认 0 认定没有切批。

## N_dense：32 批分散地址的 late 读取出现明显放大

`diagnose-ordinary-v1-N_dense-{CTX,B,P,D,DB,DP}-rewrite_rows-b0` 六份计划与 gate 均已核对。fixture 是 20 万 target、8 fragments、18 万 source（90% 更新），source 6 批、4,320,000 Arrow bytes；source keys 来自固定种子的随机排列。五个遗漏 int64 列是 c2…c6。B/DB 在 source 预读超过 131072-row 边界前未见 EOF，实际计划仍是 StreamingTableExec；B 没有在该输入上获得 V/F16 的 MemTable 选边效果。

| 候选 | mode / build | build_mem_used | probe / join 输出批数 | scan 投影 / bytes_read | late Take |
|---|---|---|---|---|---|
| CTX、B | Partitioned；target 200.0 K | 21.23 M | source 180.0 K / 32 | id,c2…c6 / 5.61 M | 无 |
| D、DB | Partitioned；target 200.0 K | 10.75 M | source 180.0 K / 32 | id / 465.5 K | 180.0 K 行，7.22 M Arrow bytes |
| P | CollectLeft；source 180.0 K | 5.14 M | target 200.0 K / 25 | id,c2…c6 / 5.61 M | 无 |
| DP | CollectLeft；source 180.0 K | 5.14 M | target 200.0 K / 25 | id / 465.5 K | 180.0 K 行，7.21 M Arrow bytes |

CTX/B/D/DB 都有两侧 Hash([id],16)；P/DP 无 exchange。所有存在的 exchange 的 spill counters 均为零。所有 scan 都读 20 万行、8 fragments，没有减少 target 行数；所有 writer 都更新 18 万、插入/删除为 0。D/DB 的 32 个 join 输出批次经过 late 后仍为 32 个 Coalesce 输出批次。DP 的 late 输出批数没有单独可用 counter，不把 join 的 25 批直接等同于 Take 调用数。

以下为独立 `pairs-ordinary-v1` 每候选三轮的**各指标中位数**，不代替 REPORT 中按 block 配对的比值统计。18 格均为 `validated_success`、hot cache、`read_bytes=0`、采样 TMP=0。

| 候选 | wall 秒 | CPU 秒 | rchar bytes |
|---|---:|---:|---:|
| CTX | 0.06751 | 0.14090 | 5,612,982 |
| B | 0.06752 | 0.14074 | 5,612,976 |
| P | 0.05866 | 0.09250 | 5,612,975 |
| D | 0.11035 | 0.59116 | 165,058,780 |
| DB | 0.11396 | 0.59705 | 165,060,782 |
| DP | 0.08815 | 0.11816 | 5,641,059 |

**已证实的工作量变化：** D/DB 减少了 scan 叶子读取与 build 保留量，但整个 execute 的文件读取系统调用字节增加到约 165 MB，CPU 增加；这不是 spill，也不是冷盘读量。D/DB 与 CTX/B 的最终数据文件同为 4,933,594 bytes，P/DP 同为 4,904,794 bytes，结果写出体积不能解释各自加 late 后的差异。即便 DP 避免了明显读取放大，它的 wall 在三轮都大于 P，说明该窄表、90% 更新场景中的 late 仍有额外成本。

**支持但尚未逐页证明的解释：** D/DB 的 source probe 保持随机 key，经 Hash 分区后各批仍可跨多个 target fragments；late 在每个 chunk 新建 TakeBuilder，chunk 之间没有在本节点合并地址或复用解码结果。现有 Take 对每次调用内部的地址排序、去重、按 fragment 分组后读取并恢复输出顺序（`rust/lance/src/dataset/take.rs:284–345`；[固定基线源码摘录](dependency-excerpts/lance-take.md)），这不能消除跨调用的相同页重读。粗略数量关系为 `32×(宽 scan 约5.61 MB−窄 scan 约0.4655 MB)+窄 scan`，接近观测的 165 MB，支持“各批重复覆盖遗漏列存储页”的解释；缩写误差、元数据及具体页读取均未逐次观测，不能把这个估算当作精确的 32 次全列读取证据。DP 从 target probe 生成更新地址，读取量回到约 5.64 MB，与较好的批间局部性相容；它也同时改变了 join mode 和执行拓扑，不能将全部收益仅归给排序。

## V_dense：B/DB 换边成立，但更少 CPU 不等于更少读取

`diagnose-ordinary-v1-V_dense-{CTX,B,P,D,DB,DP}-rewrite_rows-b0` 六份诊断及 gate 均已核对。fixture 为 10 万 target、10 fragments、9 万随机顺序 source（90% 更新），source 352 批、2,160,000 Arrow bytes；遗漏 keep_text、keep_binary、row_marker，变长字段含 NULL。B/DB 在该 source 上完成预读，实际 source 为 DataSourceExec，换到 build 侧；仍为 Partitioned，不能将“source build”简称为 CollectLeft。

| 候选 | mode / build | build_mem_used | probe / join 输出批数 | scan bytes_read | payload_take_arrow_bytes |
|---|---|---|---|---|---|
| CTX | Partitioned；target 100.0 K | 213.2 M | stream source 90.00 K / 16 | 158.8 M | 无 |
| B | Partitioned；memory source 90.00 K | 5.39 M | target 100.0 K / 16 | 158.8 M | 无 |
| D | Partitioned；target 100.0 K | 5.37 M | stream source 90.00 K / 16 | 245.4 K | 186.9 M |
| DB | Partitioned；memory source 90.00 K | 5.39 M | target 100.0 K / 16 | 245.4 K | 196.3 M |
| P | CollectLeft；stream source 90.00 K | 2.58 M | target 100.0 K / 12 | 158.8 M | 无 |
| DP | CollectLeft；stream source 90.00 K | 2.58 M | target 100.0 K / 12 | 245.4 K | 408.1 M |

CTX/B/D/DB 两侧均 Hash([id],16)，spill 全零；P/DP 无 exchange。六份 scan 都读 10 万行、10 fragments；CTX/B/P 的投影为 id,keep_text,keep_binary,row_marker，D/DB/DP 仅 id，均另带 row_id/row_addr。D/DB/DP 都 Take 9 万行、condition/reuse=0，所有 writer 都更新 9 万、无插入/删除，写出 1 文件、bytes_written 约142.9 M。D/DB 的 16 个 join 输出批次经过按软目标进行的 late 分块，分别变为 125/118 个 Coalesce 输出批次；DP 无该可观测输出批数，不能从更大的 Arrow counter 推断它调用更多 Take。

独立三轮 execute 的各指标中位数如下；18 格均 `validated_success`，hot cache、`read_bytes=0`、采样 TMP=0。

| 候选 | wall 秒 | CPU 秒 | rchar bytes |
|---|---:|---:|---:|
| CTX | 0.90044 | 1.36451 | 158,852,755 |
| B | 0.78667 | 1.25875 | 158,852,749 |
| P | 0.74996 | 1.07277 | 158,852,749 |
| D | 0.94535 | 6.58337 | 181,054,612 |
| DB | 0.80120 | 5.21983 | 219,459,509 |
| DP | 0.77181 | 0.86169 | 159,039,250 |

**先前局部性假设需要收窄：** DB 的 source build 与 target probe 已被证实，但它比 D 的 rchar 更高，约 219 MB 对 181 MB；“DB 换边后通过更少重复读取而降低 CPU”不受这组数据支持。DB 的 CPU 和 wall 较低可以与更有序的地址处理、分块数量变化或调度相容，但不能在没有地址轨迹/分阶段 profile 时确定原因；两侧 Hash 交换也仍允许各输入流交错，不能称为全局 rowaddr 顺序。

**CPU 成本不能从读字节或 Arrow bytes 单独预测。** D/DB 已把 hash join 的 join_time 降到约 5ms，却在完整 execute 消耗 6.58/5.22 CPU 秒；125/118 个 late 输出批次说明有额外读取、解码、地址处理与 gather 机会，CPU 增量主要不由更宽 hash probe 解释。还不能把总差额全部归给 Take，writer、调度与数组分配的独立 CPU 占比没有测量。DP 的 Arrow counter 最大（408.1 M），但 rchar 接近一次完整读取、CPU 最低，反例直接排除了“Arrow bytes 越大就读得越多或 CPU 越高”的解释。

三个 late 候选使用同一分块实现，实际 input partition 数不同会改变每 partition 的软目标：有限 pool/8/输入 partition 数，再限制到最多16MiB（`ports/D/source/rust/lance/src/dataset/write/merge_insert/exec/condition.rs:675–706`）。这会连同地址局部性影响 chunk 形状、调用开销和 backing buffer 记账。不能据此宣称固定一路总是更好：Wn 已给出相反的 wall 方向，而 reverse/growth 的内存责任仍须单独判断。

## 本轮新增诊断的证据边界与下一步判断

Wn 两格及 N/V 十二格全部通过文本 hash、解析结构、writer/late 计数对照；提取文件 `diagnostic-wn-ordinary-extraction.json` 保存每份文本 SHA256 和原始行号。对应 D/DP Wn 六个 execute、N/V 三十六个 execute 共 42 格独立成功。仍不把诊断 gate 当作完整 execute 证明，也不使用其时间替代配对结果。

可以据此保留三个约束：dense narrow 的 late 不能默认视为免费改进；选边、交换和 payload 读取局部性必须分开考虑；变长数据的软分块会改变调用与 CPU 成本，其代价不能只用最终写出量或 build 内存衡量。现有证据足以解释为什么单一候选难以覆盖所有工作负载，但尚未验证具体分流条件、动态 selector 或 native scan 实现。本报告不据未测反事实替任何候选宣布全面优胜。
