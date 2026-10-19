# 最终技术取舍的独立复核

复核对象是共同基线 `0a0d327` 上冻结的 B/P/D/CTX/DB/DP。已读取五个配对 plan 的 87 次成功执行及汇总，独立复算 ordinary 的六组主比较；此前已独立复核另四个 plan 的 54 个 block 比率。所有比率均为同 block 耗时相除后取三项中位数。本说明只审查本地记录与技术推论，不重新执行值 oracle，不代替完整 artifact 审计；辅助诊断尚未到齐。没有 SSH、实验或 ports 修改。

总体方向成立：**DB 是有证据支持继续整理的组合基础，当前没有证明哪个完整候选适合作为通用默认。** 必须进一步收紧的是“V_dense 只慢 2.7%”这一表述：它省内存，同时显著增加 CPU 与读取调用，不能概括成很小的总成本。建议合作整理 #10077 的重叠部分并先交可审阅补丁与证据，尚不支持另开一份整包替代 PR。这里的“建议合作/提交”是下一步建议，没有发生公开沟通，也不表示维护者已经接受。

## 1. B、P、D 分别改善什么，失败在哪里，原因能说到哪一步？

| 对象 | 本轮可支持的判断 | 需要保留的边界 |
| --- | --- | --- |
| B | F16、Wn、R_admission 完成；完整小 source 的统计准备能与正常 Auto 共存。代码保留了未 EOF 的 prefix+tail 及反向选边 | F16 仍比 P/D/组合慢；Wn 的约 125 MiB 临时文件峰值反复出现；Ws 为资源失败。100 MiB/131072 行不是硬 admission，完整 source 统计也不保证所有投影估计可靠 |
| P | F16/Wn/Ws 完成，N_dense 三轮时间低于 B；其固定 source build、单路 probe 和 scan 设置是一组有效但有范围的策略 | R_admission 在 256 MiB 下失败，不能成为兼顾反向容量的通用默认。不能把各格收益单独归给禁止 RoundRobin、某个 scan 参数或选边，而忽略其余变化 |
| D | F16、Wn/Ws 的 late 路径有明显价值；D/CTX 是当前最直接的 late 整体对照 | F64 中窄 target 仍资源失败；N_dense 明显退化；V_dense CPU 成本高。它未解决任意行数的 build 状态增长，也不是仅缩窄 projection 就自动获得正确选边 |
| DB | F64 在 D 失败的合同下成功；F16 的 DB/D 中位耗时比 0.362733，DB/B 为 0.116643；R_admission 完成 | 只能把它称为有用的组合基础，不能称为无回退的默认。N 的 DB/B 为 1.681538；Ws 的 DB/DP 为 1.392829。DB/B 还包含共同 context 的差异，不是纯 payload 消融 |
| DP | Wn/Ws 相比 P 有明显改善；Ws 比 DB 快；V 的 CPU 与内存也比 DB 低 | 继承 P 的 reverse 失败。Wn 的 DB/DP 中位比 0.705261，DP 在该格较慢；N 的 DP/P 为 1.519803。单路策略也没有消除所有 late 成本 |

F64 的单次存活检查没有构造失败/成功耗时比，旧快照校验与资源失败保留。F16/Wn/Ws/reverse 的原值、资源及临时文件区别见 [paired-audit-note.md](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/paired-audit-note.md)；全部配对值见 [paired-report.json](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/paired-report.json)。当前能确定的是组合改变了结果与成本；实际 build 来源、交换 spill、Take 局部性仍须由相应诊断支持。不能把源码允许某条路径，直接写成该次执行已经走了那条路径。

ordinary 的主结论如下。括号内是三次 block 比率的最小/最大值，不是置信区间。

| 工作负载 | D / CTX | DB / B | DP / P |
| --- | ---: | ---: | ---: |
| N_dense | 1.625570（1.577421–1.634669） | 1.681538（1.663803–1.756737） | 1.519803（1.488636–1.525781） |
| V_dense | 1.060433（1.049881–1.079867） | 1.026585（1.010290–1.027692） | 1.037752（1.003049–1.039291） |

N 中 D/CTX 的 API 中位数分别为 0.11035/0.06751 s，DB/B 为 0.11396/0.06752 s。绝对增时约数十毫秒，但三轮方向一致且超出事先约 10% 的调查门槛；D 的采样 RSS 中位数约 405 MiB 对 CTX 287 MiB，DB 约 412 MiB 对 B 303 MiB，cgroup 峰值也同向增加。CPU 各自中位数 D/CTX 为 0.59116/0.14090 s，DB/B 为 0.59705/0.14074 s。当前 D/DB 在这个普通更新格没有可见的容量收益抵偿成本。DP 的 RSS 则约 275 MiB 对 P 280 MiB，不能把 D/DB 的增内存推广成“所有 late 都增内存”。

**V 的时间接近不代表工作量接近。** DB/B 的 CPU 各自中位数为 5.21983/1.25875 s，D/CTX 为 6.58337/1.36451 s；这些是各自分布中位数的并列描述，不冒充预登记配对比率。DB 的采样 RSS 中位数约 610 MiB 对 B 964 MiB，确有资源交换，但更多 CPU 工作被当前并行机器的 wall time 部分掩盖。DB 的 `syscr` 每轮约 140.8k，B 为 141；D 约 174k，CTX 约 141。DB 的 `rchar` 约 219.46 MB，甚至高于 D 的约 181.05 MB，因此 DB 比 D 快不能证明“少读”或“更好的 Take 局部性”。DP 在 V 的 CPU 中位数 0.86169 s 对 P 1.07277 s，RSS 482 MiB 对 759 MiB，是另一种策略交互，不应与 DB 的 CPU 增长合并叙述。

36 个 ordinary 格的物理 `read_bytes` 都为 0；`rchar` 是进程读取系统调用返回字节，`syscr` 是进程读取调用次数，都不能替代 Lance Take 次数、页重访或对象存储请求数。CPU/调用数证据足以要求把执行效率纳入默认选择，尚不能证明具体成本全部来自随机读取、gather 或某个交换算子。

## 2. 应保留、撤回或组合什么？

| 建议保留的机制/合同 | 不等于现有代码可以直接合入的原因 |
| --- | --- |
| 同一 attempt 的规划、执行、analyze 共用实际 TaskContext | 这是明确的资源合同修正，但会改变原先无界增长的失败行为；需要单独说明默认 factory 额度与未记账分配。不能从 pool 生效推导 HashJoin 自动 spill 或 RSS 硬限 |
| 未知流仅在 EOF 后发布完整 source 统计，保留 Auto 的反向选边出口 | 当前 B/DB 的整批越界、缺少 batch/time 上限、未登记 source 缓存、FirstSeen/replay 生命周期仍需维护。Auto 也会使用 Inexact 估计，不能承诺始终选择更小 build |
| 对有必要容量/读取收益的范围继续保留 late 能力 | 当前 eligibility 只有类型、格式和写模式条件，没有收益门控；N 已反驳“所有合格 scalar partial Rows 默认 late 都划算”。V 的 CPU 成本还要求明确可接受的吞吐/资源交换 |
| P 对 scan 与并行资源的治理思路，以及 indexed/Columns 外围的独立责任 | P 的整表磁盘均宽估算不是窄 projection 的 Arrow 内存模型；固定 source build 失败边界明确。不能把这组代码全部复制到通用路径，或把主 Rows 成功推广到外围性能 |

建议撤回的是**当前仅凭类型资格就自动启用 payload late 的默认范围**，以及**固定 source build 作为通用默认的主张**。这不是要求删除所有 late 或否定 P 的全部贡献。本轮协议把超过 10% 作为调查门槛，并非数学上的一票否决；如果产品愿意为特定容量收益接受普通更新的成本，仍可作这种明确取舍，但不能再声称已满足原来兼顾普通负载的目标。现有 N 同时增时、增 CPU、增内存，使保留当前默认需要新的正面理由，不能仅用 F16 的收益抵消。

现在没有已验证的自动 guard。source key 数不能代替实际物理行/页覆盖，source 预读是否 EOF 也不是 late 便宜的充分条件；试完 action 再选策略要付完整输入保存、source 值驻留及可能 spill 的代价。若后续交付显式 early/late 或有限 guard，需要真正实现与验证，不能把它记作冻结 DB 已有能力。

## 3. 当前最佳基础是否完成原共同目标？

DB 在本轮的小 source/大旧表、宽遗漏字段、宽 source 和 reverse 容量格中完成，确实比只依赖 D 的窄 target 更接近共同目标。该判断依赖实际 execute 与完整值校验，不以 analyze 返回代替成功。它仍未达到普通整数 dense 低回退的目标，V 的吞吐成本也未解决。因此可以说“组合可行且值得继续”，不能说“统一 killer 默认方案已经完成”。

边界包括：本地 hot、reader、非索引、Rows 是主要配对合同；冷读仅有一次尝试驱逐的 CTX/D × V 对照；materialized 输入性能、远端对象存储和完整 indexed/Columns 性能没有由这些 87 次配对覆盖。64M 的成功不是任意大旧表或原生产数据全量的证明。当前实现没有新增 native scan、StatsGuard、按 pool 派生且有 batch 上限的预读、性能 selector 或新写回格式；不必为了符合原蓝图补齐这些部件，但也不能说原蓝图已全部实现。

正确性测试和 87 次成功配对是已完成证据；已有 7 次 pool failure、1 次 OOM 仍是容量边界。分析计划只能在对应成功 execute 后辅助解释。Lance 的 analyze helper 存在忽略流错误的既有边界，root 输出计数又不能可靠证明 writer 完成；诊断状态或 root `output_rows=0` 都不能替代提交与完整 oracle。详见 [DP-integration-review.md](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/DP-integration-review.md)。

## 4. 实现复杂度是否值得？

DB 的生产 Rust 改动为 `+647/-172`，DP 为 `+671/-169`，D 的 condition 节点单独为 `+437/-96`；这些数字来自冻结 [cost-audit.json](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/cost-audit.json)，不是预计维护时间。条件值复用、payload 候选映射、nullable 输出、软分块、错误释放与 retry snapshot 的组合生命周期具有实际复杂度。Wn/Ws 的数量级改善和 F64 的容量出口支持继续保留有关机制进行整理；它们不足以让目前所有自动默认条件也随之获准。

不应为证明既有 D 有价值立即追加 sort、collect 或 selector。N 的三轮已能决定当前默认范围不够好，无须先找到唯一 CPU 热点才允许作此判断。若最终真要交付“B + 共同 context，early 默认”的更小补丁，DB force-early 是必要的新控制，可先 N 配对、Ws 容量检查；否则它只是未测设想，当前无需扩展矩阵。若目标仍要求一个广泛自动默认，而没有可靠低成本 guard，接受“尚未得到满足全部目标的方案”比临时调整阈值更准确。

已经写下的 [EOF collect 备选](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/eof-collect-alternative.md) 不适用于本次未读到 EOF 的 N；[全局地址排序](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/sort-alternative-notes.md) 则引入 source 值屏障和 spill 成本。两者均未实现验证，不能成为本轮推荐 DB 的隐含保证。

## 5. 当前应如何贡献？

同意先整理补丁与证据、讨论与冻结 #10077 的合作或互补，当前不另开整包替代 PR。理由是 planner/context 的修改直接重叠，而 #10077 还承担 indexed 未覆盖 fragments 的 scan budget、Union→Coalesce、Full→Left/Inner 的外围 action、covering-index Take、legacy/Columns sort 与 lineage；本轮主矩阵不足以替代这些责任。保留其责任不等于宣称所有外围实现已经充分验证，也不要求为了配合它接受固定 source build 的通用默认。

可供审阅的材料应明确分开：共同 context 的独立问题与补丁；完整 EOF/Auto 出口的收益和缓存边界；late 的容量价值、N/V 代价和待定默认范围；P/DP reverse 失败及尚未完成的因果诊断。当前没有实测的 B+共享 context early 组合，不将其包装成已验证最终替代物。发布前仍须检查届时上游状态与重叠 PR；本次只读本地冻结证据，没有刷新或操作 GitHub。

三个判断应分别落判：**这批已登记配对执行和正确性校验通过；尚无通用综合赢家；证据足以提出具体合作建议和可复核补丁，不足以建议当前 DB/DP 整包按现有默认直接上游合入。** 若诊断最终推翻某个机制解释，应改解释；N 的真实结果、反向容量失败和各 workload 的取舍不会因此消失。
