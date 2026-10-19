# 默认范围与下一步实验的边界

本说明基于共同基线 `0a0d327` 上冻结的 B/P/D/CTX/DB/DP 源码，以及本地已有的第一波、N/V 补充控制记录。构建、正确性测试及补充控制已通过；下列时间均是指定 run 的单次结果，后续配对仍按 [decision-protocol.md](decision-protocol.md) 裁定，不据这里的先后顺序选胜者。本次只写说明，没有修改 ports、构建或执行实验。

当前可以推荐保留“规划与执行共用实际 context”和“完整 source 统计必须以 EOF 为依据、并保留反向选边”这两项机制。当前证据还不能支持所有合格 partial Rows 默认 late，也不能支持用固定 source build 替代 Auto 成为通用默认。是否保留 D 的具体实现由收益与维护成本决定；已经实现和测试通过不构成保留理由。

## 当前结果已经约束了什么

| 证据对象 | 已观察到的事实 | 对默认范围的约束 |
| --- | --- | --- |
| F64，1 GiB 配置 pool | D 为 `resource_exhausted`，独立验证旧快照未变；DB 完成。F16 中 D、DB 均完成，DB 首轮 RSS 明显较低 | 窄 target 的 key/address/hash 状态仍会随旧表行数增长。D 单独不能解决任意大的旧表；B 机制加入 D 后补上了本格容量出口。将其归因为实际选边还须核对最终计划，不能由结果反推精确 build 内存 |
| R_admission，256 MiB 配置 pool | B/CTX/D/DB 完成；P/DP 为 `resource_exhausted`，失败后旧快照保持不变 | P/DP 的固定 source build 有真实反向容量代价。受控失败有原子性价值，但没有完成业务，不能作为通用默认已经通过的证据 |
| N_dense | CTX 0.0664 s / sampled RSS 293.8 MiB，D 0.1095 s / 406.1 MiB；B 0.0704 s，DB 0.1127 s；P 0.0589 s，DP 0.0875 s | 单次结果提示普通整数 dense 的 late 成本，D/CTX 同时增加时间和 RSS。P 已关闭 key repartition，P→DP 仍增时，故不能把全部退化先归给 Hash Repartition；三轮前不宣布稳定回退 |
| V_dense | CTX 0.8432 s / sampled RSS 1043.0 MiB，D 0.9143 s / 620.6 MiB；B/DB/P/DP 补充控制均成功 | 首轮约 8% 增时伴随约 40% RSS 降低，属于资源与时间的取舍，不适合与 N 合并为“dense 一律不值得 late”。一次尝试驱逐后的本地读取也不能外推对象存储 |

数字来源是 `runs/survival-growth-v1-F64-{D,DB}-rewrite_rows-b0/`、`survival-reverse-v1-R_admission-*-rewrite_rows-b0/`、`survival-ordinary-v1-{N_dense,V_dense}-{CTX,D}-rewrite_rows-b0/` 与 `survival-ordinary-controls-v1-*`，对应 `metrics.json` 和 `execute-memory.jsonl`。此处 sampled RSS 取汇总的采样进程峰值，不与 `ru_maxrss`、cgroup 峰值或 pool reservation 混称；成功与失败不计算加速比。后续更新 `summary.json` 不改变上述 run 的身份。

## 可以独立推进的机制

**共同 context 是资源合同修正。** 非索引 v2 的 planner、execute、analyze 应使用同一 attempt 返回的 TaskContext，避免规划使用 bounded pool、执行却换回默认无界 pool。CTX 的接线位于 [create_plan_with_context](ports/CTX/source/rust/lance/src/dataset/write/merge_insert.rs:2621)、[execute](ports/CTX/source/rust/lance/src/dataset/write/merge_insert.rs:2820) 和 [analyze](ports/CTX/source/rust/lance/src/dataset/write/merge_insert.rs:3518)。可以独立推荐这项修正，但必须公开它会把部分旧的无界增长转成资源错误；它不保证 HashJoin 能 spill，也不限制所有 Arrow、scan、Take 或进程 RSS。默认额度仍取项目 factory，不能把改 context 包装成零行为变化。

**EOF 统计与保留 Auto 的方向有价值，纯 B 的实现边界仍要保留。** DB/F64 的成功及 reverse 的成功共同支持继续评估这条组合方向。B/DB 只有真正读到 EOF 才生成完整 MemTable，越界保持 prefix+tail；它没有伪造前缀为完整统计。该合同见 [source 准备](ports/DB/source/rust/lance/src/dataset/write/merge_insert.rs:2463)。但当前 100 MiB/131072 行是在保留整批后停止，首批可以越界；没有 batch 数或 producer 等待时间上限，缓存也未登记到 pool。纯 B 还未做到规划与执行共用同一 bounded pool。可推荐的是完整性合同与选边出口，不是宣称现有预读已经具有硬内存上界或对所有大流无额外代价。

这两项可以形成更小的基础，是否需要 late 应另判。纯 B 不能自动代替这个基础：它与 DB 的 context 不同，而且 B/Ws 已有资源失败。也不能把 B/DB 的全部性能差异归给 late。若要决定最小交付物是否只是“B + 共同 context”，需要下文的同 context early 控制，而不是借 D/CTX 的归因代替这个组合的执行证据。

## late 的资格条件还不是收益门控

当前 [DB 的 can_defer_payload](ports/DB/source/rust/lance/src/dataset/write/merge_insert.rs:2840) 检查 current v2、Rows 更新、没有 blob、遗漏字段是支持的 scalar 且无 extension。这些条件保障表示与语义，未判断命中密度、页覆盖或读取成本；所有符合条件的遗漏字段都会 late。D/DB/DP 已通过的条件、NULL、重复键、错误和真实 retry 测试证明对应语义，不证明每个合格 workload 都应默认进入这条路径。

若三轮确认 N 的回退且没有该格需要的资源收益，应否定当前过宽的默认范围；不能用 F16/F64 的容量价值抵消 N，也不能据此删除所有 late。V 的变长 payload 和 Wn/Ws 的宽值需要单独判断：early 若无法在相同资源合同中完成，late 的价值首先是容量；双方都成功时再评估时间与内存取舍。`condition.rs:675–810` 的分块只是按观察值调整下一片的软目标，late_jump 已验证的突增行为仍不能提升为 RSS 硬限。

在没有已验证自动 selector 前，诚实的交付选择是保留 early 默认，给有明确容量需求且已验证的范围显式选择 late，或者暂不把 late 放入面向通用用户的补丁。当前没有这项 early/late 公共 API，不能写成已交付能力；若采用显式选择，需要另行设计接口和默认值。不要仅用“固定宽/变长”“source 很小”或某个行数阈值自动划线：少量 source key 可以 fan out 到大量 target 行，源重复与条件会改变实际更新数，行覆盖也不等于页覆盖。通过本次 unique-key fixture 不等于生产数据具备唯一性合同。

“等所有 action 完成再决定 early/late”也有代价：必须保存 source 新值和 action，可能引入完整输入屏障、重读及 spill；未知流或大 source 不能免费获得这个选择。试取一批再切换，也需要明确已消费 source、已产生输出与目标 snapshot 的生命周期。不能把这些未实现成本藏在“以后加自适应”一句话里。

## N 若稳定回退，是否要追加策略原型

**不必为保留 D 追加原型。** 先完成已登记的三轮，读取同合同实际计划，确认进入 late 的列、最终 build 侧、join mode、分区数、Take 行数与计数完整性。D/CTX 是当前最干净的 late 整体对照，DP/P 可检查固定 P 策略下是否仍有同方向成本；DB/B 还混有 context 变化。N 的绝对差值很小，需要与方向稳定性一起报告，但小绝对差值也不允许抹去稳定比例回退。

只有一个尚未回答的问题会立即改变默认实现的选择：**在保留 DB 的 EOF 准备、Auto 和共同 context 后，移除默认 payload late，能否取得需要的 dense 行为，同时损失哪些必要容量？** 最小新增控制是在独立实验快照把 DB 的 payload 延后开关强制为 early；其余 source 准备、条件延后、写模式、context 和优化开关不动。它等价于检验当前非索引 v2 路径的“B + 共同 context”基础，不新增生产 selector，也不修改冻结候选。

如果三轮后确实需要这个答案，先只跑 **N_dense** 的同合同配对，再用 **Ws** 做一个容量检查。N 判断能否移除默认 late 的实质收益；Ws 的纯 B 失败、DB 成功，最能暴露同 context early 是否仍失去必要的宽字段出口。若拟议交付还声称覆盖 F64，再追加一次 F64 存活检查；不把失败时间纳入延迟比较。只有 N 的变体改善且容量代价被明确接受，才支持更小 early 默认；若差异很小或变体仍不满足目标，可以直接报告暂没有满足全部范围的默认方案。该控制尚未实现或测量，并非现在要求增加候选。

排序或 EOF collect 属于第二层问题，只有在默认范围仍必须覆盖的具体场景中、现有计划和计数支持相应瓶颈时才值得原型化。已经保存的 [EOF collect 备选](eof-collect-alternative.md) 只作用于完整 EOF 且已选 source-build 的 Partitioned join，当前 N 在 163840 行前缀即跨预读门槛，根本不适用；提高预读阈值让 N 恰好进入不能证明通用策略。V 若已有可接受取舍，也没有立即引入 collect 的必要。[按 row address 排序](sort-alternative-notes.md) 能改变 N 的跨批 Take 集合，但引入 source 新值的完整屏障、排序与 spill，必须保留 reverse 和宽 source 反例；它不能被当作无成本的 late 修复。当前没有实现 native scan、StatsGuard、按 coverage 选 sink 或新写回策略，它们都不计入本轮成绩。

## 维护成本与 #10077 的责任范围

冻结计数见 [cost-audit.json](cost-audit.json)：CTX 生产 Rust `+33/-8`，B `+128/-46`，D `+532/-129`，DB `+647/-172`，DP `+671/-169`。D 的 condition 节点独占 `+437/-96`；维护对象包括 action 候选映射、条件列复用、nullable payload、分块与 backing buffers、分区属性、错误传播及 snapshot 地址。测试通过使这些对象可审阅，不会消除持续维护成本。最终如果更小基础已取得必要收益，删除额外 late 层是正常结论；如果它提供 early 无法达到的容量，则应把这部分收益与明确门控一起提交，不用净增行数直接否决。

本轮 Rows 非索引结论不能替代 #10077 的外围责任：indexed 未覆盖 fragments 的 scan budget、Union→Coalesce、indexed Full→Left/Inner 后的插入及复合 key/NULL、covering-index Take、legacy/Columns sort 的 pool/context 与 column patch/lineage 语义。其代码与尚未覆盖的边界见 [cost-mechanism.md](cost-mechanism.md) 和 [test-coverage-audit.md](test-coverage-audit.md)。P/DP reverse 失败约束的是固定 source-build 的通用默认主张，不自动否定这些外围修改；DB 在主矩阵的价值也不授权把整份 #10077 替换掉。

本轮可以形成分层结论：先判断哪些机制值得独立保留，再判断 late 的具体范围，最后决定较小补丁、与 #10077 互补，或仅反馈反例和证据。允许结果是“若干机制成立，但仍无满足全部目标的通用默认”；无需为给出一个统一名称继续增加策略。
