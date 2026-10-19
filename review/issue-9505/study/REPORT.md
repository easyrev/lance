# Lance #9505 / #10077：同基线技术选择

状态：代码移植、构建与定向测试、87 次正式配对、23 次辅助计划诊断及最终现场哈希审计均已完成。以下计时来自本轮，失败及慢样本完整保留。版本、移植调整、构建与完整原始记录从 [README](README.md) 进入。

## 结论

当前没有一个已验证候选适合直接成为覆盖全部目标的通用默认。DB（统计准备 + deferred payload + 共同 context）是有价值的组合基础：它同时完成了本轮 F64 的小输入/超大旧表和 reverse 的大输入/小旧表。但它在普通整数列的 90% 更新场景稳定增加耗时与 RSS；在普通变长列上，较小的 wall-time 差异还掩盖了明显 CPU 成本。DP 在宽输入 Ws 占优，却保留了固定 source-build 的反向容量失败，也没有消除整数列的 late 回退。

因此建议与 #10077 协作，先提供本轮补丁、反例和证据，按机制讨论共同 context、选边、扫描/交换和 payload 时机。当前不建议另开一个整包替代 PR，也不把“DB 可作为下一步基础”写成“DB 当前默认策略值得直接合入”。#10077 的 indexed/Columns 外围责任继续独立保留。

## 实验对象与合同

共同基线为 `0a0d327082988018a25f56147d3b6d02f6c79ecc`。B 来自 `793e4e27119540a17ae37ce78d4f5f4d52060a93`，P 来自 #10077 的 `9e1ebc2e816a7195b56757ebe269e74989fc30c7`，D 来自 `50e216972e1558ce253bece5db462d8241fde96a`。U 不改代码；CTX 只取 D 的 context/factory 接线；DB、DP 为实际构建的组合。完整来源及 test-only 调整见 `ports/*/port-notes.md`，实际扩展 SHA 见 [VALIDATION](VALIDATION.md)。历史 f885/90d98 等 P 结果不混入本表。

ECS 为 16 logical CPU / 8 physical cores、123 GiB RAM、无 swap、本地 ext4 NVMe；所有主比较固定 reader 输入、非索引、Rows writer、新进程、8 GiB cgroup。除 reverse 的配置 pool 为 256 MiB，其余为 1 GiB。U 的实际执行 pool 无界，B 的 planning/execution pool 分开，CTX/D/DB 和 P/DP 的对应新路径使用共同执行 context；配置数值不等于全进程上限。编译与性能实验不重叠。

计时包住 `builder.execute(source)`，包括内部预读、规划、scan/join/Take、写出与提交；clone、预热/驱逐和独立读回不在计时内。正式配对每格三个随机顺序 block。先计算同一 block 的候选比值，再取三轮中位数；不使用失败时间，也不把不同组的中位数相除充当配对。原始三轮、范围、CPU、RSS、cgroup、累计 I/O、新文件和 TMP 全列在 [paired-report.md](paired-report.md)，机器可读版本为 [paired-report.json](paired-report.json)。三轮足以识别这里的大差异，不能据几个百分点宣布普遍优势。

## 同 Rows 写入下的结果

下表为三轮 API 秒数中位数，仅用于读取各候选的量级。比率结论使用后文同 block 统计。`资源失败` 来自前置同合同执行，`—` 表示没有配对，不代表失败。

| workload | B | P | D | DB | DP |
| --- | ---: | ---: | ---: | ---: | ---: |
| F16：1600 万旧行 / 44 int64 列，100 行输入 | 1.581 | 0.709 | 0.516 | 0.189 | 0.245 |
| Wn：400 旧行，5 MiB/行遗漏 payload，25 行更新 | 2.674 | 2.101 | 0.242 | 0.248 | 0.344 |
| Ws：Wn 的旧 payload，输入另带 250 MiB 新值 | 资源失败 | 3.239 | 1.779 | 1.775 | 1.275 |
| reverse：100 万旧行，300 万 full-schema 输入 | 1.861 | 资源失败 | 1.944 | 1.918 | 资源失败 |
| N：20 万旧行 / 8 int64 列，90% 更新 | 0.0675 | 0.0587 | 0.1104 | 0.1140 | 0.0881 |
| V：10 万旧行，遗漏变长 Utf8/LargeBinary，90% 更新 | 0.787 | 0.750 | 0.945 | 0.801 | 0.772 |

**小输入、大旧表。** F16 的 DB/D、DB/B、DP/P 配对时间比分别为 0.363、0.117、0.350，三轮方向一致。F16 采样 RSS 中位数 B/P/D/DB/DP 分别约 1081/801/1502/290/279 MiB。D 与 DB 的进程逻辑读取量同为约 70.48 MB；B/P 为约 3.354 GB，不能把 DB 相对 D 的收益再解释成少读了更多旧字段。U 在本轮 F16 的 8 GiB cgroup 下 OOM；CTX 在同配置 pool 下资源失败，二者没有配对加速比。

**增长边界。** F64 保持同样 44 列、100 行 source，将旧表增至 6400 万行。D 在 1 GiB fair pool 的 HashJoinInput 分配失败，source 尚未 yield；独立 oracle 校验旧版本和全部字段未变。DB 完成 100 行更新，单次 0.386 s、采样 RSS 326 MiB。它证实 D 的窄 target 仍有键/地址/hash 状态增长问题，并证实加入 B 机制能完成这一个反例；不证明任意规模有界。B/P/DP 未测 F64，不把未知格计为失败，也不计算 D/DB 加速比。

**宽字段。** Wn 中 D/B、D/P 的配对时间比为 0.090、0.118；DB/D 为 1.000，DB/DP 为 0.705。Wn 的 D/DB/DP RSS 中位数约 475/483/408 MiB，B/P 约 2627/2544 MiB。Ws 则是 DB/DP=1.393，D/DB 接近：D/DB 每轮都有 262,144,960 B 临时文件峰值，API 累计 write_bytes 约 655.46 MB；DP TMP 采样为 0、write_bytes 393,310,208 B，而三者最终新 `.lance` 都为 393,227,226 B。D/DB/DP 的 Ws RSS 仍接近 1.5 GiB。B/Ws 是 pool 资源错误而非 cgroup OOM；250 MiB 首批已跨过 B 的 100 MiB 预读停止条件，25 行不能代表输入很小。交换/落盘的节点归属见下文诊断，不仅靠文件大小判断。

**反向容量。** P/DP 失败前 producer 已记录 24 批、786,432 行；HashJoinInput 在总额 256 MiB 的 fair pool 下追加分配失败，原快照均保持不变。producer yield 不代表下游已消费相同行数，也不是独立 HashJoinInput 配额。B/D/DB 完成更新 100 万、插入 200 万，逐字段验证 44 列。DB/D 配对比为 0.986，范围 0.984–1.018；DB/B 为 1.010，未观察到稳定超过 10% 的预读回退。P/DP 的受控失败保护了原子性，但未完成业务；不能称作通用方案已通过。

**普通整数遗漏列。** CTX 的 API 中位数 0.0675 s、RSS 287 MiB；D 为 0.1104 s、405 MiB。D/CTX 的同 block 比为 1.626，范围 1.577–1.635；DB/B=1.682，DP/P=1.520。D/CTX 隔离了 late 整体，DB/B 还含 context 差异，不能单独用于归因。D/DB 的 API rchar 约 165 MB，early 对照约 5.61 MB；这些 hot 格的 read_bytes 为 0，rchar 不是物理磁盘读取。D/DB CPU 中位数约 0.591/0.597 s，CTX/B 约 0.141 s。几十毫秒绝对差值与稳定比例回退应同时报告；这格没有足够的容量收益解释 D/DB 的额外成本。

**普通变长遗漏列。** D/CTX 配对比为 1.060，DB/B=1.027，DP/P=1.038；各候选 late 都降低 RSS。CTX/D 为约 1033/619 MiB，B/DB 为 964/610 MiB，P/DP 为 759/482 MiB。但 DB/B 的 CPU 中位数分别为 5.220/1.259 s，D/CTX 为 6.583/1.365 s；DP/P 为 0.862/1.073 s。小 wall-time 差异不意味着 CPU 代价小。DB 的 rchar 约 219.46 MB，甚至高于 D 的 181.05 MB，因此 DB 比 D 快不能证明少读或更好的页局部性。

**冷读与大小突变。** 第一格驱逐尝试只测 V 的 CTX/D：逐文件 mincore after 均为 0，二者 execute read_bytes 均为 159,899,648 B；API 分别 0.913/0.965 s，采样 RSS 1009/609 MiB。该单样本没有推翻 warm 的取舍，不扩大冷读矩阵，也不外推对象存储。`late_jump` API 全字段校验通过；定向 Rust 测试保证物化器实际先见小值、后连续见大值，首次大值片达到软目标至少四倍，之后才缩为单行。它证明反馈调整存在及其过冲，不能证明硬 RSS 上限。

## 实际计划解释了什么

[诊断原文与提取表](diagnostic-findings.md)保留每个节点、指标口径及文本 SHA。这些 analyze 结果只辅助解释，完成依据仍是独立 execute 的全字段 oracle。

**F16 的互补机制已经观察到。** D 是 target-build Partitioned，保存 1600 万行，汇总 build_mem_used 约 957.4 million bytes；DB 是 source-build CollectLeft，只保存 100 行，约 4700 bytes。两者 target 扫描的行数、投影、bytes_read 相同，payload 都只 Take 100 行。B/P 已用小 source build，却仍扫描遗漏旧列；D 已缩列，却仍 build 大 target；DB/DP 在本格把两个改进合在一起。上述 build 指标不是 RSS，也不能用跨分区 build 时间相减计算墙钟收益。

**Ws 说明小 build 不足以决定全链路成本。** D/DB build 400 行窄 target，约 8 KB；DP build 25 行宽 source，约 250 MiB。D/DB 的 source probe RoundRobin 明确记录一次、25 行、250 MiB spill；DP 无该交换。RoundRobin 按整批分发，唯一一个宽 batch 没有被拆成 16 路 probe，并未获得名义分区数对应的并行。DP 同时改变选边、交换及 target 批数，具体时间贡献尚未分别消融。此格支持将 build 大小、交换必要性和实际可用并行分别评估，不能由它推出固定 source build 或 native scan 必须成为默认。

**Wn 的差异不能简单归为 16 路 Take 对单路。** D 的 source 同样只有一个窄 batch，RoundRobin 输出一批、无 spill；DP 无交换。两者都 Take 25 行，scan 投影、行数、读取量和 payload Arrow 指标相同，但 target 扫描分别形成 16 个 build 输入批与 144 个 probe 输入批。DP 的 CPU 更低、墙钟更长；批次、选边、流式背压共同变化，尚未分离各自贡献。

**普通列的回退与实际执行形态有关。** N 的 D/DB 为 target-build Partitioned、两侧 Hash(16)、32 个 join 输出批；P/DP 为 source-build CollectLeft、无交换、25 个 join 输出批。D/DB 的逻辑读取放大与离散地址分批 Take 重复覆盖遗漏列页面相容，但没有逐页轨迹，不能称为精确证明每批读完整列。V 中 DB 的 EOF 准备确实把 build 从 target 换到 source，仍保留两侧 Hash(16)；D/DB 的 16 个 join 输出批经软分块分别成为 125/118 个输出批。更小的 join 状态没有消除补列、地址处理和数组生命周期成本。DB 的读取量高于 D，DP 的 Arrow counter 最大却 CPU 和逻辑读取更低，均反对用单一字节指标解释完整耗时。具体 CPU 阶段占比仍需 profile；本轮不为解释这些数值额外扩展实现。

## 机制选择与维护成本

需要分别处理三个成本：build 侧长期保留的实际行数×投影宽度及 hash 状态；scan/交换/解码/写入中的瞬时缓冲；更新确定后按地址取得遗漏旧值的页读取与 CPU。Rows 更新最终仍须写完整新行，late 不能消除 source 新值，也不能免掉实际更新行的 payload 写入。wall time 是这些阶段并行叠加后的结果，不能用各算子 CPU 时间简单相加重建。

| 机制 | 本轮选择 | 理由及边界 |
| --- | --- | --- |
| 同 attempt 的规划/执行实际 context 一致 | 保留并与 P 的实现对齐 | 这是资源合同修正；CTX 单独仍可失败，不等于 join 自动 spill 或全进程内存封顶 |
| 未知流 source 的完整统计必须基于 EOF，保留反向选边出口 | 保留方向，不能把 B 当前准备器原样视作完善准入 | DB/F64 与 reverse 证明互补价值；当前整批越界、100 MiB/131072 行门槛、未记账 prefix、无 batch/time 上限仍存在；已物化输入不需要重新证明 EOF |
| P 的固定 source build、全局关闭相关重分区 | 不作为覆盖全部目标的通用默认 | Ws 有实测价值，但 reverse 失败；Wn 与 F16 也不能由这一套设置统一取胜 |
| D 的 late payload、条件值复用与 snapshot 地址处理 | 保留为有价值的局部机制，撤回当前无条件默认范围的主张 | Wn/Ws/F16 有明显收益；N 有稳定回退；V 有 CPU/RSS 交换。现有 guard 只是类型/语义资格，未实现收益选择器 |
| P 的整表磁盘均宽 scan sizing | 保留预算意图，不能直接当窄投影的精确成本模型 | 均值不限制解码峰值，late 后的 key/address 扫描仍沿用宽整表均值；具体优化收益尚未独立消融 |
| native scan、StatsGuard、排序、EOF collect、coverage selector | 本轮未实现，不计入成绩 | 当前证据不足以把某项设为必选；新增机制须解决已观察问题，不能为保留 D 持续加层 |
| #10077 indexed/Columns/legacy 外围 | 继续单独承担 | 本轮 Rows 主矩阵不证明全面替代；已有回归测试的范围及缺口见覆盖审计 |

生产 Rust 净增：B 82 行、P 119、D 403、CTX 25、DB 475、DP 502；这不是复杂度评分。D 的主要维护面在 condition 节点：候选映射、条件值复用、nullable payload、分块、backing buffers、分区属性及 snapshot/retry；DB 还叠加 prefix/EOF/FirstSeen/replay 生命周期。源码和按生产/测试分列的计数见 [cost-mechanism.md](cost-mechanism.md)。宽字段容量收益足以支持继续维护一个有明确范围的 late 原型，当前证据不足以支持把这些成本默认施加给所有 partial Rows。

## 还未满足的目标与下一步决策

已证实：组合的正确性和若干容量/吞吐价值；D、P 各自存在共同目标的反例；无条件 late 有普通整数列回退。合理推断：应组合可信统计与共同 context，并按负载选择 payload/交换策略。证据不足：一个能在执行前取得足够信息、代价受控的自动选择器；通用并行扩展性；远端对象存储；硬 RSS 可靠性。已物化/provider 输入的性能未测，其统计入口与本轮未知 reader 不同，不能外推 B/DB 在该入口无回退。

目前不追加排序或 EOF collect 原型来挽救默认 late。若下一步真的要交付“B + 共同 context，early 默认”，最直接的控制是 DB 同 context 强制 early：先 N 三轮，再 Ws 容量，拟承诺 F64 时再验 F64。若要承诺 V 的 CPU 吞吐，则需要单独隔离交换/局部性/并行策略；DP 整体结果不能代替这一消融。它们是有决策目的的后续实验，尚未实现或验证。

Columns writer 仍可作为符合业务语义时的替代选项，但本轮没有重新测量其性能，历史 Columns 数字不混入 Rows 候选排名。不能通过自动改写入模式来宣布当前 Rows 方案回退已经解决。

性能实验通过、综合更优、适合上游接纳应分别判断：已完成的 87 次配对都真实执行并通过独立 oracle；不存在本轮所有范围的统一赢家；证据适合拿去与 #10077 合作讨论，尚不足以建议直接合入 DB/DP 整包。没有创建 PR、发布评论或更改上游分支。

## 复核与限制

构建、选定 Python merge 语义测试、DB/DP 完整 Rust merge suite、P/DP integration、真实 stream retry 及突变测试见 [VALIDATION.md](VALIDATION.md)。不是全 workspace/全语言 CI 通过声明；本轮未将全部 Clippy/所有语言 lint 作为已通过记录。P integration 与名为 indexed 的测试存在覆盖限制，见 [test-coverage-audit.md](test-coverage-audit.md)。

依赖列表归一化后七环境相同；D 的完整列表是第一波后补采，不倒推此前完整冻结，见 [dependencies-audit.md](dependencies-audit.md)。实际 reservation 峰值、未记账数组总额和精确累计 spill bytes 不由 RSS/TMP 推算；采样可漏短峰。analyze 指标是辅助证据，独立 execute 的完整值、计数和版本 oracle 才是完成依据。

最终 [现场审计](audit-final-v1.json) 返回 `passed`，驱动退出码 0：16 份 plan、184 格记录，其中真实 execute 161、诊断 23；0 reference、0 missing、0 errors、0 warnings，实际源码、扩展、构建日志与 fixture 文件通过哈希核验。161 次 execute 中 153 次成功、7 次 pool 资源失败、1 次 cgroup OOM；八次失败均有完整 unchanged oracle。审计复核保存的断言而不重新扫描 dataset。独立 [87 格配对审计](final-pairs-audit.md) 和 [报告复核](report-review.md) 保留了各自当时的范围；后者提出的 producer、pool 配额、配对范围和 materialized 输入措辞已在本版修正。
