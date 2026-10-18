# Codex ECS 任务书：实现并验证 Lance 统一候选 C

配套主设计：lance-9505-unified-design.md。日期：2026-10-18。当前是待执行任务，没有本候选的实现或实测结果。

## 可直接交给 Codex 的任务指令

请同时阅读两份 Markdown，以主设计 v0.1 为算法和范围的唯一来源，在用户已提供的 ECS 环境中实现并验证统一候选 C。目标是评估它相对 Candidate B 和 #10077 的综合价值；不预设统计必须先合入，也不预设 native 或 Late 必须保留。

先核对连接、独立工作目录、当前仓库指令、冻结 revision 和资源能力；有现成授权就继续，不重复请求确认。若 ECS 尚未接入，先完成可做的源码实现、构建配置及 runner，准确列出尚待执行的 ECS 项。不要猜 SSH 地址、凭据或测试结果。

实施 PreparedMergeSource、merge 局部 StatsGuard 与初始选边、统一 context/P/扫描软预算、合格 target 原生分区，以及同一 proposal 中强制 Early/Late 的缺失旧字段补全原型。保持正常 DataFusion JoinSelection / Auto。先做语义和计划机制验证，再按本文有限矩阵测量；发现源码与设计假设冲突时记录具体代码证据，修订设计/manifest 后再运行受影响实验，保留旧记录。

交付实际代码、必要测试、精确复现命令、原始成功/失败记录与逐 gate 报告。一次 OOM 或确定性错误不机械重复；native 收益不足时仍可按条件验证 Cbudget+Late。完成后给出应该保留/删除的机制与剩余限制，不创建 PR、不发布 upstream 评论。

---

## 完整验证与执行规范

日期：2026-10-18。状态：**验证设计，尚未实现、构建或运行本计划**。

本文件供 Codex 在获得授权的 ECS 环境中执行。目标是检验同一 proposal 内的 **Ccore**（有界 source 准备、未知 reader 的明确选边策略、有界执行 context、统一 effective P 与扫描预算、native 多输出扫描）和 **Clate**（在 Ccore 上增加 RewriteRows 缺失列延迟读取）。下面的消融配置只是定位因果的实验开关，不是先提交一个 statistics PR 的路线。

Ccore 覆盖非索引 reader 和 materialized 输入，**包括 full-schema reverse**。完整 source、非 RewriteRows 等条件仅在相应情况下排除 Clate，不能据此把整个 Ccore 的准备或 native 路径禁用；native 自身的顺序等 guard 另行检查。

**v1 的资源合同是有界 DF pool，加上基于宽度的软估计和既有调度约束。** `Bdecode`、rows sizing 及据此算出的 memory cap 不构成全进程硬上界。I/O 沿用已有 shared `running_stream` scheduler，保持每个 base 内既有共享范围，不同 base 可以独立。v1 不引入全进程 global credits/admission，也不要求给所有既有队列新增字节记账。native 的义务是同 P、同配置时不把 scheduler 或每路 `buffered(N)` 重复扩张；真实峰值以 DF pool、active decode、RSS/cgroup 和有针对性的诊断验证。

这里的通过门槛是建议预先登记的工程决策标准，不是已有结果。主设计负责定义算法、可用内存的来源、unknown reader 的策略及各 guard；执行者先把这些决定冻结到 manifest，再开始计时。若实现发现必须改变它们，应新建 revision 与结果集，保留先前记录。

当前默认参数快照：预读 `B = min(100 MiB, Mpolicy / 8)`、`R = 128 Ki rows`、`K = 1024 batches`；`small_fixed_target` 的模型阈值为 `min(32 MiB, Mpolicy / 4)`。后者使用实际 target 投影的建模宽度与内部行数，是启发式，不是 build 内存上界；不能用整表 44 列代替 full-schema reverse 实际需要的 target 投影。参数定义以主设计的冻结版本为唯一来源，manifest 记录其 revision 与实际解析值，后续修改不得只改本文件或沿用旧结果。

## 1. 冻结证据，不继承旧主机假设

| 对照 | 固定 revision | 用途 |
| --- | --- | --- |
| U：未经修改的 main | `dc53d5d174af62c49ddd98d1024a64488c1e4404` | 原问题和用户现状的参照；不是遵守指定 DF pool 的受控对照 |
| B：旧的小流统计实现 | `793e4e27119540a17ae37ce78d4f5f4d52060a93` | 已有 source 统计、有界 context、原扫描路径的工程参照 |
| P：#10077 与冻结 main 的合并结果 | `f8859373d5022eedea239db2fcfd68713a423762` | 已有内存/吞吐方案；不能把整个差异归因于某个优化开关 |
| #10077 原始 head | `9e1ebc2e816a7195b56757ebe269e74989fc30c7` | 解释 P 的来源；不在另一条 base 上另测一次后混用标签 |
| 调查材料 | `3fd5356239b91c0d38e818b0c7237e9545d1db11` | 下列原始报告与 harness 的固定快照 |

旧报告的 160 次 execute 包括 134 次验证成功、16 次 pool 不足和 10 次确认 OOM；不是 160 次通过，更不是 C 的实验结果。旧测试是本地暖缓存、通常两个独立进程重复，极宽列低限额仅一次。它们可用于选择有辨别力的场景，不能作为新主机、新二进制的配对样本。[REPORT](https://github.com/easyrev/lance/blob/3fd5356239b91c0d38e818b0c7237e9545d1db11/review/issue-9505/REPORT.md)

不要假定 `/mnt/lance/issue-9505`、现成数据集、systemd 权限、SSH 地址、root、代理脚本或旧 Python 环境仍可用。先确认用户提供的连接方式和授权范围，在获准环境内发现路径与能力。没有连接能力时，交付本地原型、构建/运行说明和待执行 manifest，不伪造 ECS 完成状态。**先只读核对历史 `matrix.sh`、`run.sh`、`statistics-matrix.sh` 等；在适配本次路径、变体、参数和正确性校验前，不将历史 pipeline 当作一键脚本直接执行。**

## 2. 必须先修正的测量陷阱

1. **U 的非索引路径使用无界 pool。** 给它设置 `LANCE_MEM_POOL_SIZE=1 GiB` 并不使其遵守这个额度。其成功和 C 的 `ResourcesExhausted` 不能解释成同一资源合同下的可靠性退化。
2. **`LANCE_BYPASS_SPILLING` 不是纯 pool 开关。** 当前 context 实现还随该分支改变 sort spill reservation、disk manager 配置和 context 缓存/新建行为。纯 pool 消融必须在其余 SessionConfig、RuntimeEnv 和 context 生命周期一致时只更换 pool 实现；不能通过环境变量绕开整条构造路径。[exec.rs](https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance-datafusion/src/exec.rs)
3. **旧的小 reader 并不代表慢生产者。** 它先构造 Arrow table，再包装成 reader；只有旧 full-schema streaming 源才在消费时继续生成。必须另加真实惰性、可延迟且可计数的 source。
4. **旧 full-schema reverse 的正确性检查不足。** source 与 target 的生成器复用 seed，旧检查只核行数/动作计数，没有逐字段验证全部更新值。新 source 必须带不同 epoch/seed 或必然不同的值，并验证变更，排除相同内容走 NoOp 的可能。
5. **`analyze_plan` 返回不代表 execute 成功。** 旧路径会吞流错误。schema-only explain 也不能代表实际 reader/materialized 输入的最终计划。计划诊断、真实 execute 和读回验证必须分开记状态。
6. **旧汇总器只认识旧标签及两次重复。** 新 runner 要由显式 run manifest 驱动；不能让新变体、失败记录或第 3–5 次重复被静默遗漏。

以上均来自已读取的 [harness.py](https://github.com/easyrev/lance/blob/3fd5356239b91c0d38e818b0c7237e9545d1db11/review/issue-9505/harness/harness.py)、[run.sh](https://github.com/easyrev/lance/blob/3fd5356239b91c0d38e818b0c7237e9545d1db11/review/issue-9505/harness/run.sh)、[summarize.py](https://github.com/easyrev/lance/blob/3fd5356239b91c0d38e818b0c7237e9545d1db11/review/issue-9505/harness/summarize.py) 和 [REPRODUCE](https://github.com/easyrev/lance/blob/3fd5356239b91c0d38e818b0c7237e9545d1db11/review/issue-9505/REPRODUCE.md)。

## 3. 最少的原型配置与可解释的相邻比较

保留 U/B/P 三个现成对照；C 只做一套实现，用内部实验配置产生以下五种模式，不增加五套产品路径或公开参数。

| 标签 | 与前一配置的唯一区别 | 使用范围 |
| --- | --- | --- |
| Cprep∞ | C 的完整 source 准备、unknown policy 和语义 guard；canonical context；现有 v2 单输出扫描（native 关闭）；仅 DF pool 为无界 | 小型 pool 诊断。禁止对它展开大内存矩阵 |
| Cprep | 将同一 canonical context 的 DF pool 改为有界，其余保持一致 | 确认有界 pool 的实际生效，以及原扫描保留的内存问题 |
| Cbudget | Cprep 加入设计中的扫描/解码软预算与 rows sizing，仍使用 现有 v2 单输出扫描（native 关闭） 输出方式 | 分离扫描参数的影响 |
| Ccore | Cbudget 再启用 guarded native 多输出扫描 | proposal 的主要综合候选 |
| Clate | Ccore 再启用 guarded RewriteRows 缺失字段延迟读取 | 宽列分支；先内部 force early/late，未验证前不声称 auto 策略更优 |

Mpolicy 是按原请求解析出的有限名义 pool 大小。Cprep∞ 与 Cprep 必须固定同一个 Mpolicy 及派生出的 source/scan 参数；仅实际 pool 实现和限额生效状态不同。manifest 分别记录 Mpolicy、实际 pool 类型和实际限额，不能把无界 pool 代入策略公式。

所有 C 配置保持同一 source 准备算法、未知 reader 选边策略、优化器配置、写模式和语义 guard。Cprep∞/Cprep 的 SessionConfig、sort reservation、disk manager、context 新建/复用策略也必须相同；只有 pool 类型不同。若不能做这个窄注入，则明确记录为 bundled context 对比，不发布“仅 pool 导致……”的因果结论。

**Cbudget/Ccore 的比较必须固定同一 effective P、扫描软预算/宽度估计、解码及 batch/coalescing 配置、既有 scheduler 拓扑和目标快照。** 同一消融格内，Cprep∞/Cprep/Cbudget/Ccore 都先由同一策略得出并使用同一 effective P，避免在 Cprep→Cbudget 时混入另一组默认分区数；U/B/P 则保留原样并记录其实际参数。effective P 在创建 context 前确定，同值传给 context、provider 和 scanner。软预算降低 P 的场景尤其要检查，不能 native 局部降到 2 路、context 仍要求 16 路，随后被 DataFusion 补上 RoundRobin。若现有单输出接口无法保持等量并发，应如实将该边标为“输出拓扑＋并发实现”的组合变化，不宣称纯粹消除了 shuffle。

先比较相邻配置，后比较 Ccore 与 B/P。不做开关的全排列。也不默认增加“禁用全部优化器”或 `P=1` 变体；只有具体异常需要解释时才加一个定向诊断，并记录它回答的问题。Clate 默认比较相同资源设置下的 Ccore early；**若 native 机制正确但收益未达保留门槛，late 验证仍继续**，只新增一组有明确理由的 `Cbudget+late` 对 `Cbudget`，避免把无收益的 native 强绑到 late。组件是否进入最终方案由对应因果边与回归决定，不退回 statistics 先合的路线。

## 4. Gate 0：环境、构建和执行身份

在执行任何性能矩阵前完成：

- 只读确认可用 CPU、cpuset、CPU quota、内存、交换、内核、存储介质、文件系统、cgroup 版本与委派能力；确认可用磁盘空间和独立工作目录。systemd/cgroup 不可用时，只做能真实完成的测试，并把硬限额 gate 标为未验证。
- 为 U/B/P/C 建独立 checkout 与 Python 环境，遵循各 checkout 的 `AGENTS.md`、`python/AGENTS.md`。不修改他人现存 worktree、cache 或数据集。先构建完所有进入同一比较的二进制，再跑 benchmark；benchmark 期间不得同时编译。
- 冻结 commit、dirty diff、`Cargo.lock` hash、关键源码 hash、构建日志和 Python 扩展 hash；记录真正导入的模块路径及版本。C 的运行日志还要打印短 revision 与实验配置，防止沿用旧二进制。不能只凭 build exit 0 就认定当前 venv 加载了它。
- 使用同一优化 profile、toolchain、依赖、allocator 与 CPU features。历史使用仓库 `release-with-debug`，不是开发 profile；新执行者先核对 checkout 中确实存在该 profile。
- runner 外部协调者保存计划、子进程退出状态与阶段标记；子进程在独立可验证的资源边界运行。不能因 OOM 丢失整个实验清单，也不能用退出码 137 单独推断 OOM。

旧记录已验证过的命令包括仓库根的 `cargo test -p lance --lib dataset::write::merge_insert -- --test-threads=4`、`cargo fmt --all`、`cargo clippy --all --tests --benches -- -D warnings`，以及 `python/` 下的 `uv run --no-sync pytest python/tests/test_dataset.py -k merge_insert -q`、`uv run --no-sync make lint`。它们是已知入口，**本计划没有运行它们**。新增扫描/late 路径测试要先查找实际模块和现有测试，再记录真实调用；不要臆造测试名。

Python 新 worktree 的首次 Python 工作遵守当前 `python/AGENTS.md` 的 `make install` 入口。旧文档中的优化安装 override 与 [profile.mk](https://github.com/easyrev/lance/blob/3fd5356239b91c0d38e818b0c7237e9545d1db11/review/issue-9505/harness/profile.mk) 可用于核对构建方式；不能照抄旧绝对路径、代理初始化或 uv 地址。[根 AGENTS](https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/AGENTS.md)；[Python AGENTS](https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/python/AGENTS.md)

## 5. Gate 1：小型语义与机制验证

优先扩展现有测试，使用小数据和确定性计数/时钟/故障注入。这里描述测试义务，不预先发明函数名。慢 source 不靠长时间 sleep 做单元测试。

### 5.1 Source 准备、统计、未知输入和重试

- EOF 内 materialize 才发布精确总行数/字节信息；按实际 `B/R/K` 覆盖字节、行数、batch 数阈值下、恰好达到及越过，并覆盖 FirstSeen 的相关限制。若主设计另行承诺 deadline，再验证时间边界。超限但未见 EOF 的前缀不能冒充完整统计。一个超大 batch 的真实驻留及超限行为必须可见。
- source 记录每次 poll、产出 batch、取消与 drop。覆盖空 batch 连续流、极小 batch、首 batch 延迟、前缀后永久 Pending、前缀后报错及取消。有限 batch 次数不等于有限墙钟等待；若主设计声称 deadline，必须验证 pending poll 如何安全退出/保留，及截止后是否还继续拉取。
- 超限回退精确重放“已读前缀＋后续流”，顺序不变、不重拉、不丢行、不重复；错误在应有阶段返回。schema/写模式/lineage 参数错误要先于 source 的第一次读副作用暴露，保持已有错误优先级。
- 在输入真实未知且大于准备界限时，直接检查最终选边依据/策略标签。用真实 lazy 3M reader 的反向规模用例验证，不用预先物化获得的统计替代。
- 初始 join direction 在 `plan_extension` 中确定，随后保留完整 DataFusion 优化流程和 `Auto`。同时记录初始方向、决策依据和优化后的实际方向；不能以强制关闭 JoinSelection/repartition 的方式让测试通过，也不要求优化后永远保留初始左右位置。
- 对 `small_fixed_target` 阈值做计划级上下界验证，记录实际投影、内部真实 rows、宽度模型及阈值解析值。unknown reader 的 full-schema reverse 必须实际走其应有策略；阈值匹配仅证明策略实现正确，不能证明 hash table/临时分配受模型字节数硬约束。
- **StatsGuard 的双 Absent 合同**：当 target 的实际投影含未建模的变长/嵌套字段时，对优化器公开的 `total_byte_size` 与 `num_rows` 都是 `Absent`；真实 rows 只留在内部策略/sizing 中。固定宽度或未投影这些字段的组合按设计保留可用统计。不能只隐藏 bytes、继续把很小的精确 rows 提供给 Auto collect 的行数回退。
- **统计 registry 开/关**：分别检查直接读取 wrapper 统计和 registry 路径的结果；两者都必须保留上述双 Absent。简单 wrapper 不声明 cardinality `Equal`，避免 registry 绕过 wrapper 从 child 恢复 rows。执行者查明当前 DataFusion 控制 registry 的真实入口并记录配置，不臆造开关名。此处的开/关是小型机制测试，不新增完整 benchmark 变体。
- FirstSeen 的胜者按原定义的 source 顺序确定，跨 batch/partition 重复 key 带不同 replacement 值；不能把 native worker 抢先完成者当 first。覆盖 Fail 策略、NULL、空 source、取消和已有冲突 retry 行为。若 FirstSeen guard 回退，日志须证明回退生效且语义正确。
- indexed 等明确排除 Ccore 的组合保持既定路径；非索引完整 source、full-schema reverse、其他支持写模式分别验证 source 准备和 native 自身 guard，不统一要求它们回退。非 RewriteRows、source 已含全部目标字段及其他 late 排除条件只检查 Clate 不触发；顺序敏感扫描则检查 native 自身的回退。不能只看输出相同而不检查实际 hook。

**Auto collect 反例必须单列。** 使用 target **200 行 × 5 MiB 旧 payload**（约 1000 MiB），source 则为**首批 25 行 × 10 MiB、跨过 Bpref 且未观察 EOF 的真实 reader**；source 必须更新另一个已有字段，并遗漏这个旧 payload，防止投影已经把旧 payload 裁掉。这个用例联合验证 Prefix 状态、初始方向和 StatsGuard。先用不实际分配约 1 GiB payload 的计划级 fixture 展示：只将 target bytes 置 Absent、保留 rows=200，Auto 仍可能单侧 collect target；双 Absent 时，registry 开/关都不能恢复这个虚假的“小 target”判断。断言基于优化后的实际模式/方向及公开统计，不能只检查 wrapper getter。真实数据只在 ECS 做一次启用完整 Guard 的机制诊断并读回验证；不把它放进轻量单元测试，也不实际执行危险的 bytes-only 反事实路径。

### 5.2 Context、预算和 native P

- 以小型、已知 build 所需数据超过指定 DF quota 的 fixture 比较 Cprep∞/Cprep：前者在宽裕的外部内存边界内完成，后者在明确 consumer 处返回资源错误；同时证明普通小 source 可以在小 quota 下成功。不得把一次 schema 错误或别的 allocator 失败当作 pool 通过。
- 每次 execute 内，planning 和 execution 共享设计要求的实际 pool/context；记录 context/pool identity 和该 pool 的 reservation。独立 analyze 调用可使用自己的 context，但有效配置必须等价。涉及 DF consumer 的新增路径不能悄悄另开完整额度的 pool；这不意味着要求不同 base 的 I/O scheduler 合并成一个。
- 记录 requested P、effective P 及 context/provider/scanner 实值。覆盖软估计使 P 降低和 P=1 的边界；记录 `Bdecode`、rows sizing、宽度估计/memory cap 和 active decode。检查同一 base 的 shared `running_stream` 身份/作用域在 native 前后保持一致，不能变成每个输出 partition 一个独立 scheduler 或一份 `buffered(N)`。不要求所有既有队列的字节计数先完备。
- guarded native 路径对跨多个 fragment 的输入，合计扫描/输出行不丢不重；按物理 row identity 校验。动态领任务后，不得把平均分片行数标成每个 partition 的精确值。
- 符合共享 build 的 CollectLeft 场景验证 build 实际建立一次，不被 P 份完整复制；Partitioned join 则验证每份分片的累计输入正确。不能要求所有 join 都采用 CollectLeft。
- 保存最终执行计划或等价运行证据，验证 native 分区数，以及边界上是否仍有额外 RoundRobin；“source 支持 repartitioned”本身不算动作发生的证据。
- 不均匀 fragment、单个大 fragment、慢解码任务、任一 worker 报错和下游提前取消均能按已有机制结束，无死锁或持续存活的新增任务。记录 active decode 与实际峰值；软估计被超出时分析 width 误差、单 cell/batch 及现有缓存，不把它直接判为违反一个并不存在的全局字节 quota。

### 5.3 Clate 的额外义务

- 以相同初始快照分别强制 early/late，对缺失字段做逐物理行等价校验。目标的相同 join key 可以对应不同旧 payload，source 顺序可以非单调，跨 fragment take 必须取回正确目标行的旧字段。
- 验证 matched/unmatched 行、删除/插入动作、FirstSeen、重复 source key 的错误策略、NULL 和更新条件。按真实支持范围使用 guard；不支持的组合要有可观察回退，不扩大语义承诺。
- 对 take 前后错误、取消及冲突重试，验证未完成 merge 不提交逻辑变更；允许已有实现留下未引用临时文件，不把它们误报为已提交数据丢失。
- 验证 late 的 take 并发、结果重排及临时 buffer 的实际影响，沿用主设计指定的现有参数与 DF pool；不为满足测试额外实现 global credits。读取的行地址来自此次操作所用快照，不能在扫描与 take 之间换成另一版本。未记账 buffer 仅在峰值异常时定向 instrument。

任何行值、动作语义、错误传播、任务无法结束或 scheduler 被按 P 意外复制的问题，立即停止该配置后续性能测试。先修复并重新冻结 revision，再恢复受影响的 gate。

## 6. Gate 2：一次运行先证明机制

以下每格先运行 **1 次**，只用于检查能否进入预期路径、完成/失败原因和运行器是否可靠，不据此决定几个百分点的胜负。正式测量按下一节选择，不复制成全标签矩阵。

| 场景 | 先跑配置 | 区分什么 |
| --- | --- | --- |
| 小型已知 build 超 quota | Cprep∞、Cprep | 纯 pool 生效；不扩大到全量目标 |
| W-auto：200 × 5 MiB target；未知 reader 首批 25 × 10 MiB，遗漏旧 payload | Ccore；registry 开/关以计划级测试为主 | Prefix 状态、初始方向和双 Absent 联合生效；bytes-only 反事实只检查计划 |
| F4：4M × 44 int64、40 fragments，100 行窄 lazy reader | U、B、P、Cprep、Cbudget、Ccore | 原 build 问题、扫描预算、native 动作；U 仅作现状参照 |
| R：100K target/4 fragments，真实 lazy 3M 全列 source，必然改变值并插入剩余行 | B、P、Ccore | unknown reader 的反向选择及 source 准备屏障 |
| Wn：400 行、5 MiB 旧 payload/行、16 fragments；25 行窄 source | Cprep、Cbudget、Ccore、P | pool 之外的旧宽列扫描驻留，native 是否重复 scheduler/buffering |
| Ws：同一目标；25 行各 10 MiB 新值的 source | Cprep、Cbudget、Ccore、P | source 单 batch/总体宽度、错误 target 估计和最小可执行内存 |

普通 F4 可先用 1 GiB DF pool 与 8 GiB cgroup；R 用同一 1 GiB pool、宽裕且记录精确值的外部边界，例如 16 GiB；Wn/Ws 先用 1 GiB pool、8 GiB cgroup。这些是建议的新运行设置，执行前检查主机可承受，禁止并发叠加运行造成额外压力。

W-auto 的实际执行也先用宽裕的外部边界，并保持主设计的 StatsGuard 启用。固定一次真实 execute 证明动作/输出正确即可；registry 分支和 bytes-only 反例不展开到所有版本、资源与重复数。

已确认的确定性资源错误只需保留一次完整证据，无须重复 5 次制造相同失败。若看到 OOM，保存 cgroup/journal 证据并停止该配置该资源格；不要把重试成功当作覆盖了原失败。只有原因不明确时做一次定向复核。

## 7. Gate 3：小型、分块、配对的核心比较

所有比较来自同一冻结环境和 workload。先完成 3 个独立进程的随机配对块；机制和差异稳定后补到 **5 块**用于正式报告。每个块内随机或轮换配置顺序，跨块保留顺序表。不要按 variant 连续跑完所有 workload。接近决策边界时最多补到 9 块；仍不明确就报告未能区分，不无限追加直到出现想要的结论。

正式配对比值定义为同块 `r_i = candidate_merge_seconds / control_merge_seconds`，主比较报告 `median(r_i)`，并保留各块原值。某一侧失败，该块是失败配对，不填造 latency 或静默替换；汇总成功样本的中位数时同时显示计划/完成/验证成功/各失败状态的分母。

| 必需问题 | 正式 workload | 最少配置 | 说明 |
| --- | --- | --- | --- |
| 统一方案能否修复主场景并从 native 获益 | F16：16M × 44、160 fragments、reader 100 | B、P、Cprep、Cbudget、Ccore | 这是唯一默认把三条 C 相邻边都做正式计时的主格 |
| 原有有统计输入是否退化 | 同一 F16，materialized 100 | B、Ccore | source 准备时间另计；P 只在要声明该输入下竞争优势时增加 |
| unknown source 实际很大时是否仍能完成 | R：真实 lazy 3M 全列 source | B、Ccore；P 留 Gate 2 状态 | 若 P 在 1 GiB 下确定失败，不需要重复失败。要比較 P 的成功吞吐，另建所有版本均为 8 GiB pool 的格，不跨额度比较 |
| 预读界限及 unknown 回退是否正确 | F4，100K 及 1M 窄 lazy source | B、Ccore，先各 1 次 | 100K 检查界内 EOF 统计；1M 应因 `R=128Ki` 停止预读并验证 unknown policy，不能预期它被完整物化。仅对决策依赖的代表格补重复 |

旧 F64 是扩展验收，先不跑 U 的高 RSS 路径。只有 Ccore 通过以上 gate、确需证明扩展趋势时，才补 B/P/Ccore 的 64M reader100（同机正式重复），并报告真实新结果。不能把旧 U64 的 44 GiB 数值拼进新 C 的比值。

FirstSeen、非均匀 fragment 先通过小型正确性；随后各选一个 F4 尺度 smoke。若出现吞吐或内存异常，才扩成 Cbudget/Ccore 的正式配对。fragment skew 要包含“少数 fragment 占大多数行/字节”和“热点匹配行集中在少数 fragment”，不能只把同样大小的 fragment 数增加。

## 8. Gate 4：宽列、安全边界与 Clate

先让 Ccore 在 Wn/Ws 上暴露瓶颈，再做 Clate 的有意义配对。Clate 的实现和小型语义测试属于本 proposal 的交付；不是要先发布 Cprep。性能矩阵只在有辨别力的宽列格展开。

若 Gate 3 只证明 native 收益不足，保留其机制结论并继续 late：在下表中选最有辨别力的一格，新增 `Cbudget+late` 对 `Cbudget` 的相邻比较；必要时再补一个高覆盖率反例。不要因 native 未过性能门槛而中止统一 proposal，也不展开 `native × late × 所有预算` 的全组合。下表默认写 Ccore/Clate，启用这个分支时在 run manifest 明确替换基座。

| 格 | 目标/匹配特征 | Ccore early 对 Clate 的问题 |
| --- | --- | --- |
| V-sparse | 2M 行、20 fragments，旧 payload 长度独立采样 128 B–2 KiB；少量窄 source | 普通变长列能否节省真实读取字节，还是协调/take 成本主导 |
| W-sparse | Wn 的极宽旧字段，25 个匹配 key，非单调 source 顺序 | 延迟读取能否减少旧字段驻留/扫描量；不是 source 已提供全部字段的伪 late case |
| W-dense-duplicate | 同样宽度层级；目标重复 key 分散在 fragment 内外，少数热 key 命中约 90% 物理行；每行旧 payload 带可区分标记 | 输入 key 数很少但物理覆盖率很高时，late 是否产生大量随机 take、重排和重复读取 |

先各 1 次，确认 early/late 都进入强制路径、更新相同物理行；只对决定保留 late 和设计 guard 的格补 5 次配对。高覆盖 fixture 的数据量可先缩小，保证安全后放大；不要为了复用旧 target 把“100/4M 个 key”误当成“100/4M 行覆盖率”。

重复 key fixture 应另有不参与 join、每个物理行唯一且不会由 source 替换的 `row_marker`，与旧 payload 一起进入 oracle。不能继续沿用旧 harness 的唯一 `id` 生成器，然后把多个相同 source key 当成已经覆盖目标重复 key。

核心记录旧缺失列实际 scan/take 的行数、字节数、已有请求/并发指标，以及 RSS/cgroup。重排 buffer 峰值与更细 I/O 等待先使用已有计数，仅在 late 的峰值或延迟异常且需要归因时新增定向 instrument；不要求先补齐全部队列记账。只有 wall time 降低而没有路径证据，不能宣称收益来自 late materialization。重复 key/高覆盖率是 auto 策略的反例搜索，不能在训练该阈值的同一两格上宣布策略普遍有效。若预测命中率、字段宽度或 I/O 成本仍不可靠，交付内部 force 模式和有限 guard，明确 auto 未验证。

### 独立低内存格

- F4/reader100：256 MiB DF pool、2 GiB cgroup、swap=0，Ccore 必须实际执行成功并读回正确；这是已知 B/P 已成功过的代表格，新环境仍需重验。
- Wn/Ws：1 GiB DF pool、2 GiB cgroup，先 Ccore，再对设计允许的情况测 Clate。任何 OOM 都否决“该格受控”的声明。若现有错误路径（例如 DF pool reservation 失败）返回资源错误，记录为可控资源失败，**不属于 workload 成功**；v1 不要求新增能事先判定最小工作集的 admission 框架。
- 若 8 GiB cgroup 下 Ws 仍因错误 build 估计在 1 GiB pool 失败，记录为 candidate 的执行边界；不能用 2 GiB 下的可控失败抹掉高限额下仍未解决的功能问题。

process 既有内存、调用者已物化 source、不可拆的单个 cell/batch 可能大于软估计。报告观察到的工作集、超大项和 width 模型误差；无法事先保证的部分明确保留边界，不为通过 gate 发明准入机制。DF reservation 合规不自动证明 RSS 不超限；有限几次 cgroup 通过也不证明任意工作负载的全进程硬上界。

## 9. 慢 source 的单独延迟合同

ECS 上另做小数据的真实 generator 诊断，记录 producer 各 batch 的 ready/poll 时间、首次 planning 完成、首次 target 读取、首次写出与总 merge 时间。至少覆盖首 batch 慢、前几批快随后慢、永不 EOF 的测试源（由外部受控取消结束），以及准备预算刚触发时的边界。

这些实验验证的是“优化为了拿统计增加了多少启动等待”及回退行为，不是高吞吐评分。固定各版本相同 producer 时间表，报告准备额外等待和端到端时间，不能把 producer 等待全部算作 join 退化，也不能把它排除后声称用户延迟无变化。无法取消的 pending poll 必须明确暴露为合同限制；batch 数上限不能冒充时间上限。

## 10. 测量合同与状态模型

### 时间、动作与正确性

- `merge_seconds`：`execute` 的 wall time，含实际 planning/source 消费/writing/commit；排除 fixture 生成、恢复初始快照和结果验证。另存其中的 `source_prepare_seconds` 子区间、CPU 秒数和平均 CPU 核数；不要把已包含的准备时间再次相加。若 materialized source 在 execute 外构造，单独记录 `input_materialization_seconds`，需要端到端比较时明确加上它；该字段不混入旧 API-only 口径。延迟诊断分段时间单列。
- 每次运行从已知初始 snapshot 开始，source 更新值保证不同。记录更新/插入/删除计数、最终行数、版本/提交与所有预期行的字段内容。对未被更新的行/字段，用流式校验或稳定 hash 证明保持原值。source 宽 binary 必须验证内容 hash，不能只查 length。
- full-schema reverse 逐字段检查或基于确定性 row oracle 校验。FirstSeen 保存预期 winner；late 以物理行身份区分同 key 的不同旧字段。执行成功必须同时满足 `execute_returned` 和 `validated=true`。
- 运行状态至少区分 `validated_success`、`resource_exhausted`、`confirmed_oom`、`source_error`、`validation_error`、`timeout/cancelled`、`infrastructure_error`。单独 analyze 为 `diagnostic`，不能进入成功分母。
- execute 完成后先固化资源计数和阶段标记，再用单独受控的 validator 验证，防止把读回过程 OOM 误记成 merge OOM。即使验证在另一进程中，也只有验证通过后才算成功。

### 内存与 I/O

| 类别 | 原始记录 | 解释边界 |
| --- | --- | --- |
| DataFusion | pool 类型/额度、该 pool 当前/峰值 reservation、consumer 名称及峰值、context identity | 只反映纳入 pool 的分配；不能当全进程内存 |
| Source / native 核心计数 | source prefix bytes/rows/polls、requested/effective P、active decode、每个 base 的 scheduler 作用域及扫描配置 | 验证预读停止条件和 native 不重复 scheduler/每路 buffering；不把任务数直接等同于精确驻留 bytes |
| 软模型参数 | `Bdecode`、rows sizing、投影宽度估计、memory cap、small-target 模型值与阈值 | 解释策略及估计误差；不是所有队列的全局硬 quota |
| 进程 | 10 ms RSS/RssAnon/RssFile/RssShmem；执行前基线；Linux `ru_maxrss` | Linux ru_maxrss 单位 KiB，转 bytes；包括初始化/准备。RSS 差值不是精确 allocator 归因 |
| cgroup | 精确 `memory.max`、swap 设置、`memory.current/peak`、`memory.events` 增量、可用时 ancestor 事件与完整 unit/kernel 记录 | cgroup 限的是进程组、cache 等，和 RSS 不相等；共享页的 charge 可能在别的组 |
| 算子/I/O | 实际 build/probe 行和字节、build 次数、output P、scan/take bytes、spill 临时字节、请求数/读 I/O | 区分扫描、重分发、take、重写收益；logical rows/s 不是物理存储吞吐 |

一律保存整数 bytes，显示时显式使用 MiB=`2^20`、GiB=`2^30`。不要把十进制 GB 的算子值与 GiB RSS 混为一谈。以新子进程/资源组或明确重置方式隔离峰值；采样值在 OOM 后只是下界。pool 和扫描预算应同时列出，不用一个含糊的 “memory=1G” 标签。

核心计数优先使用已有指标或最小计数器。未记账的 scan/decode/take/output 队列，只在 RSS、active decode 或吞吐出现具体异常时定向 instrument；不能把全队列记账变成 v1 的交付前置条件。详细事件 trace 和 analyze 可改变开销，放到独立 diagnostic run。性能 run 使用各变体一致的轻量计数与采样；若只有 C 加了昂贵 trace，必须关掉后测正式延迟。算子 `elapsed_compute` 可能嵌套、并发，不能简单相加重建 wall time。

## 11. Hot/cold 与重复隔离

默认先本地 hot cache，保持与旧问题相近的读环境。每次只预热**初始快照实际引用的数据文件**，记录 manifest；不要通配预热目录里重写失败遗留的所有 `.lance` 文件。数据生成、恢复与预热不在计时区间，资源 charge 方式在所有版本中保持一致。

冷缓存单独形成结果组，不与 hot 混算中位数。不假定可以全局 drop cache；那会影响其他工作。可在授权的隔离环境中采用可验证的 evict 方法，记录实际读 I/O。`posix_fadvise` 等建议性动作、换文件名或拷贝文件本身都不能证明真正 cold；不确定时标签写“尝试驱逐后的本地读取”并给 I/O 证据。

Clate 的远程对象存储对照为可选：仅在已授权 bucket/endpoint 和隔离测试前缀存在时运行，同一对象、缓存策略、并发、连接复用条件下比较 early/late；记录请求数、range 大小、字节量、延迟和费用相关请求计数。没有该环境时，明确仅证明本地结果，不伪造远端性能或据此调 auto 阈值。

不得并行更新同一数据集，也不同时跑多个内存格。将核数、CPU quota、后台任务、频率策略、热状态和运行顺序写入环境记录。性能中断后保留块编号，不能把不同环境的半块拼成配对结果。

## 12. 预先登记的通过与否决门槛

### 硬 gate

1. 所有声明支持的语义和真实 execute 读回正确；一次错误结果、FirstSeen winner 错误、重复/丢失物理行、已失败操作却提交，立即否决该 revision。
2. Ccore 在 F4/F16 小 reader 与真实大 reader reverse 的既定 1 GiB pool 合同下完成；reverse 不要求某个固定算子文本，但不能以无界 source build 或被吞错误冒充完成。若只能提升 pool 才过，必须明确改了资源合同，不能算原 gate 通过。
3. tracked DF reservation 遵守实际 pool；effective P 三层相同，软预算降低 P 后不被额外 RoundRobin 扩回；native 没有为每个 partition 复制既有 shared scheduler 或完整 `buffered(N)`。`Bdecode`/rows sizing/memory cap 的计算与主设计一致，但不把观测 bytes 超过软估计直接判为违反全局硬 quota。StatsGuard 双 Absent 在 registry 开/关下有效，Auto collect 反例通过。
4. 2 GiB fixed 场景成功；所有声称在该资源格受控的压力测试无 OOM。现有机制的可控资源错误可以作为结果，单列失败率/覆盖边界，不当成完成业务操作；不要求实现 v1 之外的 admission 或所有队列 credits。
5. Clate 通过与 early 的完整语义等价，并在宣称受益的格实际减少预期旧字段读取或驻留；若性能样本只是未进入 late 路径或 NoOp，整格作无效实验。高覆盖率格中 late 更慢或读取更多仍是有效反例，应保留。

### 决定是否保留复杂度的性能标准

- 建议把 F16 的 native 保留门槛设为：Ccore 对相同 P/扫描配置的 Cbudget 至少 **10% 中位 wall time 改善**，且配对方向稳定；报告全部配对比值、范围以及有条件的 bootstrap 区间。5 次只能识别较大效应，不应宣称精确几个百分点。接近门槛时补到最多 9 次，仍不明就记录“尚未证明 native 的额外复杂度有收益”，并进入有理由的 `Cbudget+late` 对 `Cbudget` 分支，继续验证 late。
- materialized 控制、reverse、skew 与 FirstSeen 若出现稳定 **超过 10%** 的 wall time 退化，暂停扩大矩阵并解释原因。不是用一个大胜格平均掉另一格退化；设计若因资源安全接受某项吞吐成本，应在报告中明确该决策及代价。
- Ccore 对 B/P 的同合同成功格报告真实 wall/RSS/CPU；P 关闭优化器后的整体优势不被解释为单一 shuffle 成本。Ccore 是否接近或超过 P 是结果，不预设必然成立。
- native 不得因实现复制而随 P 重复整个扫描/build 工作集。相邻配置的 RSS/匿名内存若增加超过 10% 且超过 32 MiB，先检查共享 build、per-base scheduler 是否被复制及 active decode，再对可疑 buffer 定向追踪；这个值是调查触发点，不是以 RSS 推导 DF pool 或软估计是否违规的公式。
- late 只在它实际有收益的格宣称优越。稀疏宽列改善而重复 key 高覆盖率明显变差时，应收窄 guard 或维持 force 模式，不强行启用 auto。若 local 与 object store 方向不同，应由适用条件解释，不混合平均。

以上百分比是工程取舍的预注册建议，允许在**看到正式结果前**由主设计明确调整并记录原因。不得测完后移动阈值来包装成功。

## 13. Codex handoff 的实际执行次序

1. **接入与发现**：确认授权连接和工作目录，保存环境/权限能力清单；读取当前 checkout 的 AGENTS；只读导入冻结证据。连接缺失就输出待执行项，不猜 SSH/root。
2. **实现与冻结**：实现统一 Ccore、Clate 与最少内部消融；沿主设计填全 `B/R/K`、unknown policy、StatsGuard/registry、软参数、effective P 解析和超大 batch 边界。补必要小型测试，记录源码/补丁 hash；不扩成 global credits/admission 项目。
3. **构建与正确性**：按真实仓库入口构建优化 Python 扩展；确认加载身份；完成 Gate 1 和相关既有回归。保存实际命令与日志，不复制旧通过数字。
4. **新 runner**：依据上述合同复用经过核对的生成/测量模块，补齐最小 runner/校验器，使用新的 run manifest 和结果目录。生成稳定 fixture 与 row oracle；先用极小数据检验状态、限额与读回记录。
5. **机制 smoke**：按 Gate 2 一次一格；每次核查 actual action、pool/预算/P、实际选边、失败 consumer、输出正确。任何混淆先修正后继续。
6. **核心配对**：先 3 块，满足条件后补到 5；完成 F16 主格、materialized 控制和真实 reverse。决定 native 是否值得保留，不先发布 statistics 分支；只有 native 性能门槛未过时，继续使用 Gate 4 的 `Cbudget+late` 分支。
7. **宽列与 late**：在已确认语义正确的基座上，执行 Gate 4 的 early/late 定向配对、压力格及慢 source；失败时先缩小 guard/修正策略，不立即扫更多规模。native 与 late 独立依据相邻因果边决定是否纳入最终方案。
8. **有条件扩展**：仅为尚未回答的承诺补 F64、cold、对象存储或更强 skew。没有承诺需求就停止扩展，不重复完整历史 160 次矩阵。
9. **审阅交付**：汇总所有状态及配对比较，逐 gate 给出通过/否决/未验证；列出可支持的 PR/简历表述、仍未解决的边界和建议保留的配置。此任务不创建 PR、不发 upstream 评论。

## 14. 必须输出的文件

以下为执行阶段**应创建的文件**，本设计不声称它们已经存在。实际根路径由发现阶段决定，并写入 runbook。

| 文件 | 最小内容 |
| --- | --- |
| `RUNBOOK.md` | 已验证的绝对路径、实际构建/测试/执行命令、授权范围、各 gate 的执行顺序与恢复方法 |
| `manifest.json` | U/B/P/C revisions、patch/source/binary hashes、构建 profile、主设计 revision、`B/R/K`、small-target 阈值、StatsGuard/registry、软参数、单元与结果 schema 版本 |
| `environment.json` | 硬件/OS/toolchain/存储/allocator/cgroup/CPU quota/cache 方法及缺失能力；不包含凭据 |
| `workloads.json` | seeds/epoch、字段和 payload 分布、fragment 分布、初始 snapshot、source 真实惰性属性、预期物理覆盖率、oracle 定义 |
| `run-manifest.jsonl` | 每一个计划/已执行格的 run ID、block、配置、source/cache/资源参数、effective P、状态；失败格也必须保留 |
| `logs/` | 实际构建/回归/限额能力核验日志；旧失败、新失败、修复后结果分开命名 |
| `runs/<id>/metrics.json` | 分阶段时间、CPU、原始 bytes、source bytes/rows/polls、P/active decode、pool peak、scan/take bytes、build 次数、实际动作和终态 |
| `runs/<id>/memory.jsonl` | 带单调时间戳的 RSS/cgroup 采样；flush 使被 kill 后仍可分析 |
| `runs/<id>/execution.log`、`resource-events.json` | 完整退出/错误 consumer/cgroup 事件与阶段标记；避免只留 journal 最后几行 |
| `runs/<id>/validation.json` | 更新/插入/删除/总行数、字段/内容 hash、FirstSeen winner/物理 row 校验、是否实际改变值 |
| `diagnostics/` | actual-source 计划、StatsGuard/registry/Auto 反例、source poll、native/task/scheduler/late 路径证据及必要的定向 buffer 调查；与计时 run 分开 |
| `summary.csv`、`REPORT.md` | 所有成功/失败计数、同格同合同配对比值、hot/cold 分组、gate 决定、允许及不允许宣称的结论 |

汇总应明确区分“旧证据”“新实测”“设计推断”“未验证”。当前任务交付的是这一验证方案；其后 Codex 的最终报告不得将本文件的预期计划或门槛改写成已完成的测试结果。
