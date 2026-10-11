> Historical report. Status statements describe the stage when this report was written. See the [review index](../README.md) for the published branch context. Only links were adapted below. The [original report](../evidence/independent-performance-script-audit.md) remains byte-identical.

# 性能实验执行前独立审计

本轮只读检查脚本、原始 baseline 计划、构建和 detector 校准证据，没有在编译期间运行计时工作负载。生产 commit 保持 `26632629ca162cdbfd82dabad1d80e3e6c92b364`。

确认一个会影响解释的缺口：原脚本将 conflict 的总 wall time 作为主要比较值，但没有说明其中包含随机重试等待。`rust/lance/src/dataset/write/retry.rs:81-90` 将首轮失败前的总耗时乘以约 1.1 作为时槽长度。`rust/lance-core/src/utils/backoff.rs` 的 `SlotBackoff::next_backoff` 在首次重试随机选择 0、1、2、3 个时槽。两次相邻的 baseline/candidate 测量不共享随机槽；五次重复的 conflict wall-time 中位数变化可能主要来自等待差异，不能单独归因于 replay 优化。

建议在最终测量前记录第一次 commit hook 进入时刻，并展示总 CPU、首次 hook 前 CPU 和耗时。第一次 hook 计时应结束于竞争更新之前，包含第一轮 merge 工作；它不是隔离的 replay 耗时。保留全部原始 conflict wall time，并明确其中包括随机等待和竞争更新。该修改只增加仓库外证据观测，不改变生产重试行为或固定随机数。

同时建议把 timed conflict 的 commit 版本断言由“至少两次”收紧为 `[2, 3]`，检查最终 inserted/updated/deleted 统计。原 fixture 的竞争操作重写已被当前 merge 读取的唯一 target 行，配合本轮既有 factory 计数测试和重试源码，能够支持完整重新执行的判断。仅有 commit hook 调用次数不足以区分语义重试和提交重试，前期纯 append 夹具已经显示了这一限制。

其余已核对的证据约束：

- baseline/candidate 使用相同 fixtures、Arrow 版本、线程上限及本地预热方式；每次独立进程，五轮交替先后顺序，汇总保留全部样本。
- 两个 fixture 分别为 1.125 MiB 和 132 MiB，跨越 replay 的 100 MiB 内存阈值；256 字节控制输入验证有缓冲但不落盘的情况。
- detector 观测 `.tmp` 目录创建与 spill 文件删除。源码中 replay 创建前必建该目录，校准栈落在 Lance `TempDir::try_new`；one-shot、materialized、opaque Scanner 和 zero-retry 控制提供交叉约束。目录缺失结合该代码路径和正控制，可以支持未进入 replay 机制。
- 实际计划来自同一输入的 `analyze_plan`，单独运行且检查没有提交。归一化保留 join 类型和算子。图形相同不意味着缓冲相同，因为两条路径都使用 StreamingTable。
- `release-with-debug` 构建、冻结 Python 包和 ELF allocated section 比对提供匹配产物依据。最终运行还须核对 candidate 的相同记录。
- RSS 是进程至 merge 完成的高水位，不能直接叫作 replay 内存。I/O 统计包含目标写入和内核取消写，不能解释成物理设备字节。报告模板已经注明这些边界。

该审计不对最终性能收益作判断。最终还需审查全部原始测量、配对波动、fallback 对照、最终 candidate 计划及本次脚本修订结果。

修订复核：`benchmark.py` 现记录 commit hook 进入/退出、首次 hook 前 wall/CPU、竞争更新耗时及总 CPU，并严格断言版本和三项 merge 统计。`summarize.py` 保留这些原始样本和分布，报告模板明确随机槽与未隔离的成本。静态检查确认 first hook 计时发生在竞争更新之前。

为检查字段和控制流程，独立运行了 8 行、256 字节 fixture 的 clean/conflict 诊断 smoke。它们使用已核对的 DEV 扩展，label 为 `independent-review-diagnostic`，不会被 baseline/candidate 汇总器选中。两项均退出 0，stderr 为空；额外断言验证事件先后顺序、首次 CPU 不大于总 CPU、版本分别为 `[2]` 和 `[2,3]`，merge 统计为插入 7/更新 1/删除 0。原始记录为 `independent-backoff-smoke-clean.json`、`independent-backoff-smoke-conflict.json` 及同名 stderr。这些诊断发生于编译期间，不构成性能样本，不用于速度结论。

执行前审计发现已在证据脚本层面处理。探针日志本身也有系统调用开销；若最终小输入仅出现微小时间差，仍需结合 fallback 波动谨慎解释，必要时才做无记录探针的窄范围复测。
