# DP：完整 P 移植与 D 延迟补列的组合

共同基线为 `0a0d327082988018a25f56147d3b6d02f6c79ecc`。P 来源为 `9e1ebc2e816a7195b56757ebe269e74989fc30c7`，其真实 parent 是 `8d77df617e85687567e9529fbc5520f793783e78`；先完成 `../P` 的同基线移植，再叠加归档 D 实现提交 `50e216972e1558ce253bece5db462d8241fde96a`。这不是历史 C，也没有加入 C 的 source preparation、StatsGuard、native scan 或 admission selector。

## 组合规则

P 决定非索引 join 的 source build、target probe，以及关闭 join reordering、join repartition、RoundRobin repartition。P 的 MergeBudget、扫描 I/O/rows 公式和 partition 设置原样保留。D 只改变符合条件的旧 payload 何时进入数据流，并复用条件已经读取的值。

`create_plan_with_context` 从 P 的 MergeBudget 取得规划所用 session，调用 P 的 `create_plan_in` 后返回该 session 的 task context。真实 execute 和 analyze 均使用这个 context；不会让 D 另建一个默认 session 覆盖 P 的配置。D materializer 从实际 context 读取 pool/batch 参数，因此它的软切片参数来自 P 的真实配置。

D 的 `condition.rs` 和 `logical_plan.rs` 与归档提交逐字相同，SHA256 分别为 `9f875074...`、`65e11ed6...`。保留其标量遗漏字段 guard、按最终 UpdateAll 补值、条件列复用、原行映射、nullable 占位、snapshot 与 lineage 处理，以及全部原单元测试。

P 的 Python 文档/测试、table-provider I/O 接口和原内存集成测试四个文件与纯 P 产物逐字相同。`merge_insert.rs` 中的索引未覆盖 fragment 预算、Coalesce、Left/Inner join 及列补丁单 partition 排序也保留。

## 六处合并冲突及处理

1. execution imports：保留 P 的 SessionContext 和 D 的 TaskContext；不保留仅旧测试 seam 使用的 SessionConfig。
2. plan constructor：以 P 的 MergeBudget/create_plan_in 为主体，增加返回实际 context 的 wrapper；不使用 D 独立创建 session 的路径。
3. execute 创建 plan：改用组合 wrapper。
4. execute task context：使用 wrapper 返回的 P context。
5. analyze：使用 D 的 `analyze_plan_with_context` 并传入实际 P context。
6. partial-schema plan 断言：保留 source build，改为检查窄 target 和 `payload=[other]`。

没有修改原 P 的预算常数、选边策略、scan fan-out 估算或外围 writer 行为。

## 测试兼容调整

P 的 partial-schema 计划快照原本要求 target scan 含 `other`，与 D 延迟补列冲突。组合测试明确检查 target 仅扫描 key、materializer 生成 other、CollectLeft/Inner，以及 source 子树在 target 子树之前。P 的两类 source 固定 build 测试继续保留；修正混入的 D 注释，避免描述成默认优化器自适应。

D 的 1 MiB 测试原本要求未知宽 source 流式 probe、小 target build 成功。这个预期与 P 的核心策略互斥，不能偷偷修改生产选边来通过它。DP 改为 `test_unknown_wide_source_exhausts_fixed_source_build_pool`：相同 source/target 尺寸，保留 P optimizer 配置并使用显式 1 MiB pool，要求实际计划返回资源错误，再刷新 latest snapshot 检查版本及旧值。它是预期失败机制的测试，不表示业务操作成功，也不替代主任务的真实 API reverse 测量。

该测试中的常量断言采用已审阅的 `const { assert!(...) };`，避免归档 D 已知的 Clippy 错误。这一修改位于 cfg(test)。没有删去 D 条件复用、NULL、chunking、retry、duplicate 等测试。所有新增/调整的测试仍待实际构建运行，错误显示文本和最终计划检查不能提前算通过。

## 可归因范围与限制

- P 与 DP 的差异用于观察延迟补列及条件值复用，并包括 analyze 实际 context 共享的修正；计时若使用真实 execute，该 context 在 P 中本来已共享。
- DP 的扫描 batch rows 仍根据 P 的全表磁盘平均行宽估计，即使 target 实际投影已经只剩 key/identity。因此 DP 可能继续使用过小的扫描批次；本轮刻意保留这一设置以免同时改扫描策略。
- D 只能减少旧 target payload，不能缩小 source 新值。P 在大 source / 小 target 的固定 source build 限制仍存在；soft chunking 不能修复它。
- D 的类型与格式 fallback 不变：遗漏嵌套/集合/扩展类型或任意 dataset blob 等情形回退 early；这里只覆盖符合 guard 的遗漏标量字段。
- pool、scan/decode 软目标、Take/gather 切片和 RSS/cgroup 是不同边界。没有新增全进程内存准入或 HashJoin spill。
- indexed 和 RewriteColumns 外围完整保留，但本轮非索引 RewriteRows 格不执行这些路径。结果不能证明这些外围已验证，更不能声称 D 替代了它们。

## 产物与本地检查

`source/` 包含七个修改文件的基线相对路径，`implementation.patch` 可以直接应用到共同基线。`mechanism.json` 保存来源、冲突、调整、每文件与补丁 SHA256。

已在由 `git show 0a0d327` 生成的文件树上完成 `git apply --check`，并在另一个临时副本实际 apply 后逐文件比对 source 字节；P 的四个外围文件及 D 的两个物化文件也已逐字比对。没有运行 build、test、lint、SSH 或 benchmark。原工作树与冻结 K 未修改；主任务负责后续构建、计划/语义 gate 和测量。
