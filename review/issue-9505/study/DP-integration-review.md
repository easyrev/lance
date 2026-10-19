# DP 组合静态审查

审查时间：2026-10-19。范围为冻结的 P、D、DP source 与共同基线 U，重点检查 join 换边、外连接动作、late condition/payload 字段映射、扫描预算、执行 context、analyze 和 retry snapshot。本次未修改候选、未运行测试、未构建、未 SSH。以下“有测试”只表示冻结源码含对应断言，不表示本次执行通过。

**结论：未发现阻断当前非索引 RewriteRows 对照实验的确定组合语义错误。** DP 保留 P 的 source-build/scan budget，把 D 的 late payload 接到同一条 v2 计划；没有发现 source/target 互换后取错列、把插入行拿去 Take、或 retry 沿用旧地址的代码路径。仍有一个明确的证据边界：`validated_diagnostic` 不能证明 analyze 完整执行成功，不能用来替代独立 execute + 值 oracle。

## 冻结对象

所有路径均相对本报告目录。共同基线为 `0a0d327082988018a25f56147d3b6d02f6c79ecc`。本次实际读取并计算的 SHA-256：

| 对象 | SHA-256 |
| --- | --- |
| `ports/P/implementation.patch` | `01a2e89d24c345b7f5e09a6a531c1d5a1a7075d064b37f78f867755dd1b8703c` |
| `ports/D/implementation.patch` | `75959c78df6f4354592d8e38fdd8b6e76314c69f2496862b0729a165ba5e0a31` |
| `ports/DP/implementation.patch` | `7ebb5bf8a2d64467cfbf306661b4aed20aa587837f0a5c1d20e87735b544f56c` |
| `ports/DP/source/rust/lance/src/dataset/write/merge_insert.rs` | `f42be3d3759b0e83bff846991ae25054c48759c2972c3e4d3745e692ddca9025` |

`cmp` 确认 D 与 DP 的 `merge_insert/exec/condition.rs`、`merge_insert/logical_plan.rs` 完全相同；P 与 DP 的 `datafusion/dataframe.rs` 完全相同。DP 对 P 的生产差异集中在 `merge_insert.rs` 的 payload eligibility/DeferredConditions 和返回 TaskContext 的计划入口，未见外围生产逻辑被组合时顺手改写。下文 `M`、`C`、`L`、`T` 分别指 DP source 下的 `merge_insert.rs`、`merge_insert/exec/condition.rs`、`merge_insert/logical_plan.rs`、`datafusion/dataframe.rs`；“U:”表示从上述基线核验的未修改文件。

## 组合语义核验

| 核验点 | 代码证据与判断 |
| --- | --- |
| source-build 与 outer actions | `M:2603–2620` 按 `(保留 source-only, 保留 target-only)` 返回 Inner/Left/Right/Full，`M:2830–2835` 的实际顺序是 `source JOIN target`，两者一致。U:`merge_insert/assign_action.rs:143–197` 用限定名 `source.__merge_source_sentinel` 和 `target._rowaddr` 判定来源，不依赖左右列序或可为 NULL 的 join key。未见换边后把 target-only 当 insert 的问题。 |
| 条件读取 source/target 同名列 | `M:2821–2829` 仍将含 target 依赖的条件延后；`L:331–345` 把优化后的逻辑输入 schema 与物理输入一起交给 materializer。`C:94–102` 检查物理/逻辑列名顺序；`C:286–327` 只重绑定 target 或未限定的 dataset 列，显式 source 引用不进入 target Take；`C:155–184` 通过逻辑索引收集 source 输入，并保留限定名构造条件 schema。没有固定的 target-left 列位置假设。 |
| 投影裁剪与最终写回 | `L:225–285` 保留必要 source 字段、target row address/id/创建版本和 action，裁掉其余 target payload；`M:2860–2896` 满足 D 的类型/格式条件时只登记遗漏列，不注入 NULL 占位。`C:219–276` 拒绝重复或已经存在的 payload 列。U:`exec/write.rs:491–598` 按字段名和 dataset schema 顺序组织写回列，不依赖源字段在 join 左侧还是右侧。 |
| update/delete/insert 混合批次 | `C:351–402` 只对 UpdateAll 候选和 source sentinel 为 NULL 的 Delete 候选求条件，Take 前拒绝 NULL target address；`C:442–461` 将 FALSE/NULL verdict 改为 Nothing；`C:464–549` 仅给最终更新行补旧 payload，其余行得到 NULL。条件结果按原输入行位置回填，source-only 插入不会读取 target。仅 target-only DeleteIf 取过的值也不会误当更新行缓存。 |
| P 扫描预算保留 | `M:1216–1280` 保留 P 的 source-build 优化器设置、IO 份额及磁盘平均行宽推导；`M:2740–2753` 将其挂到 target provider；`T:170–235` 在同一 scanner 应用 batch/io 设置、投影、过滤并调用 `create_plan_with_session(state)`。D 没有替换为另一套 target scan，也没有漏掉 P 的设置。 |
| 规划、执行、analyze context | `M:2713–2720` 每次只建一个 MergeBudget，将其 SessionState 用于规划并返回该 session 的 TaskContext；`M:2940–2951` 直接用它执行；`M:3638–3645` 向 `analyze_plan_with_context` 显式传入同一个 context。U:`lance-datafusion/src/exec.rs:798–803` 虽会额外创建一个默认 session，但提供的 TaskContext 优先使用，没有换回第二个 pool。P 原执行入口已使用自己的 budget context；DP 此处主要补齐 analyze 与 D materializer 的接线。 |
| retry snapshot/address | `M:3704–3711` 每次 clone job 后重新 `execute_uncommitted_impl`；`M:3762–3764` 替换 job.dataset。U:`write/retry.rs:53–59,92–95` 在每次执行前注入最新 dataset，冲突后 checkout latest。新计划的 target provider、write node 和 `C:402–409,496–503` 的 Take 都来自该次 dataset；未缓存上一轮 action batch、Take ProjectionPlan 或 row address。 |

上述 context 判断仅涉及计划树和其执行 TaskContext。target scanner 的解码、Take 返回的 Arrow allocation 和 writer 保留批次并未因此全部进入 DataFusion pool。`C:670–685` 明确把 byte target 定义为软目标；不能将“共用有界 context”解释成进程 RSS 或全部临时对象的硬上限。

## 现有定向断言及未验证边界

冻结 DP 包含以下组合相关测试：`M:11475` 的 `test_partial_schema_plan_builds_on_source` 同时检查 CollectLeft、source 在 target 前、窄 target projection 与 payload node；`M:11524` 附近的 `test_merge_plan_uses_canonical_memory_pool` 检查实际返回 context 的 pool 并执行；`M:17004` 的 mixed condition/insert/delete/duplicates 测试检查真实全字段结果，含 FirstSeen；`M:17080` 的 retry 测试明确使竞争写移动 row address，断言第二次尝试保留新 snapshot 的 payload；`M:7736` 的 NULL/lineage 测试矩阵覆盖四种 outer 保留组合及 partial source。`C:830,1051,1583` 还覆盖条件复用、target-only delete 缓存隔离与仅对 target-only 行求 DeleteIf。

未在本次审查中重新运行这些测试，也未用静态断言替代最终候选的 build/test 证据。以下边界需要在结论中单列：

- P/DP 固定 source build 保留了“小 target、巨大未知 source”可能比 U/D 更早 pool failure 的行为。`M:11570` 已有预期资源失败且 snapshot 不变的测试。这是候选机制本身的限制，不能因 DP 加了 late payload 就称为自适应选边，也不是组合移植错误。
- P 的 batch rows 来自整个 dataset 的磁盘平均行宽，不是 D 裁剪后 projection 的真实解码宽度。DP 可能为很窄的匹配列保留过小批次，影响 dense 或小 payload 的性能；文件压缩、变长数据、缺失元数据和 16 MiB IO 下限也使该模型不能证明内存硬上界。应由实际 scan batch/IO/时间证据解释，不以预算注释推定。
- 本轮非索引 Rows 对照不能外推到 P 的索引 join 或 Columns 排序路径。现存 composite NULL 测试只给一个 join 字段建索引时会走 fallback；两个 join 字段均有索引且含 NULL 的 indexed post-filter 语义仍是已识别的外围覆盖缺口。本审查未发现该缺口由 D 组合引入，也没有新增测试或扩大候选。
- retry 的静态接线和保留的移动地址测试支持 snapshot 重新绑定；不能据此声称已验证任意外部 TableProvider 的重复扫描稳定性。一次性 source 的 replay/禁用重试仍由基线入口决定（`M:2538–2587`）。

## analyze 证据边界：确定存在，未修改冻结 harness

U:`rust/lance-datafusion/src/exec.rs:806` 用 `while (stream.next().await).is_some() {}` 消费 AnalyzeExec，忽略其中 `Err`，随后另行 `format_plan(analyze)`。DataFusion 54.1 的 `physical-plan/src/analyze.rs:206–209` 原本通过 `transpose()?` 传播输入错误；错误是在 Lance helper 中被丢弃。DP 的共用 context 修正没有修复或引入此行为。源于输入 stream、hash build、Take、文件写入或结束阶段的错误都不能仅靠“返回了计划字符串”排除。

当前 harness 的 `validated_diagnostic` 严格只说明：API 返回、worker/import identity 等运行条件通过、producer 全量生产记录与预期行数相符且未截断、独立 oracle 验证原快照未变（`harness/harness.py:503–516`）。其中 producer 在 `yield batch` 前记账（`harness/fixtures.py:99–105`）；没有单独的 EOF 或消费者完成标记。因此“全量生产记录”也不能独立证明每行已经过 join，更不能证明 analyze 完成写入。

现有 analyzed-plan 的 root 指标不能补上这个缺口：

- U:`exec/write.rs:1195` 创建 `_baseline_metrics` 后没有用它记录 `record_output`/`record_poll`；成功路径最后返回一个 0-row batch（`1435–1444`）。root `output_rows=0` 在成功和失败时都可能成立，root `output_batches` 也未被记录，不能判成功。
- `num_updated_rows`、`num_inserted_rows`、`num_deleted_rows` 在逐行处理时累加（`192,227,248`），完整计数之后仍可能在写文件、lineage 或 apply_deletions 阶段失败。`bytes_written`、`num_files_written` 在 `1403–1408` 才累加，是更晚的进度证据，但没有 completed 标志；合法零写入也无法据此区分。
- DataFusion AnalyzeExec 只有在输入全部成功后才产生最终报告 batch，但 Lance 返回接口丢弃了 batch 与错误，只提供重新格式化的计划字符串；当前 artifacts 没有可供可靠恢复该成功状态的最终 batch 计数。

因此，只把同一候选、fixture、模式、source 形态、pool 等合同下已有独立 execute + 全字段 oracle 成功的 diagnostic 用于辅助观察计划与计数。检查计数是否符合该计划的扫描/连接/动作语义，检查 materializer 的 condition/payload Take 与复用计数是否符合条件接受率；计数不完整时标为不可用于完整执行归因。即使计数一致，也不把它升级成 analyze 完整成功证明。正式性能、存活性和正确性结论仍来自真实 execute 记录。
