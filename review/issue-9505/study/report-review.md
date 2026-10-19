# REPORT 草稿独立复核

复核的 [REPORT.md](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/REPORT.md) SHA256 为 `9222735e0e517b89c5f9f5e7e135bc23bb006d3017e46302b0b637184b30afac`。对照 `paired-report.json`、`final-choice-review.md`、`diagnostic-findings.md` 及 reverse/F64 原始 result；没有 SSH、实验、构建或修改 REPORT/README。

没有发现会推翻主要取舍的算术错误，用户的五个问题均有回应。表中 API 中位数、配对方向、CPU/RSS 数字和失败格区分一致；没有把 DB 的组合价值等同于现代码直接合入，也没有用 V 的小墙钟差掩盖 CPU 成本。建议以下两处精度修正，并补齐一项决策边界。

1. **第 38 行把 producer 观测写成了下游消费量。** `survival-reverse-v1-R_admission-{P,DP}-rewrite_rows-b0/result.json` 只证明 producer 日志累计 24 批、786432 行；该记录明确不测量 downstream retention。错误说明 HashJoinInput 在总 fair pool 为 256 MiB 时追加分配失败，也不代表它有独立固定 256 MiB 配额。建议改为：“失败前 producer 已记录 24 批、786432 行；HashJoinInput 在总额 256 MiB 的 fair pool 下追加分配失败，旧快照均保持不变。”不影响 reverse 失败结论。
2. **第 17 行的“三个 block”应限定正式配对。** 本文还引用 F64、cold、late_jump 与存活检查的单次记录，后文虽已分别说明，但“每格三个随机顺序 block”容易扩大到这些格。改成“正式配对每格三个随机顺序 block”即可。同理第 53 行的 EOF 合同应限定“未知流 source”；已物化输入本身已有完整性证据，不要求再预读一次。
3. **“还未满足的目标”应明确已物化输入性能未覆盖。** 全文声明主合同为 reader，但用户需要决定机制的默认范围，不能仅靠读者反推缺口。当前结果不能证明 B/DB 对 materialized/provider 输入性能没有回归；其入口本来就可能有统计，EOF 准备的收益前提不同。建议与远端对象存储、并行扩展性一起直接列为未验证。这不要求现在追加矩阵。

F16 的诊断现在可以提供一条确定的解释，建议合入最终文本，不必把所有因果统一留为“待补”：D 的实际计划为 target-build Partitioned，build 16M 行，`build_mem_used=957.4 M`；DB 为 source-build CollectLeft，build 100 行，`4.70 K`。D/DB 的 target 投影、扫描行数及 scan bytes_read 相同。它支持“EOF 准备与窄扫描在 F16 互补”的解释，且反驳“DB 比 D 又少读了一批旧 payload”。这里是十进制 generic metric 缩写，不要按 MiB/KiB 解释，也不要把 diagnostic 汇总 build 时间相减当作 wall-time 收益。Ws/N/V 的细粒度成本仍按各自到齐的诊断裁定。

最终取舍还应守住三条反方边界：

- N 的回退支持收窄当前默认范围，但不是普遍否决所有 late 的定理。若应用愿意为必要容量接受代价，仍可明确选择；当前不能声称已经满足原共同目标。REPORT 已基本保留这个区别。
- DB 比 DP 更适合作为继续工作的基础，来自测到的容量覆盖与机制可组合性，不是所有 workload 的时间/CPU 最优；DP 在 Ws、V 的优势必须保留。反向失败也不自动否定 #10077 的 indexed/Columns 外围。
- “B + 共同 context、early 默认”尚未作为一个候选实测。第 66 行将 force-early 留作有条件后续控制是正确的，但“唯一直接改变”可改成“最直接的控制”，避免把一种实现形式写成唯一实验。无须为了保留 D 增加 selector，也不能把未实现 guard 当作现 DB 默认已经安全的理由。

现场 hash 审计和其余 diagnostic 未完成时，报告继续标记待完成是准确的；网络中断不改变已经落盘的配对数值，也不能替代待完成的现场复核。
