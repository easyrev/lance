# P：#10077 的同基线移植与机制审计

本产物将 [#10077 固定 head](https://github.com/lance-format/lance/commit/9e1ebc2e816a7195b56757ebe269e74989fc30c7) 的完整改动移植到 `0a0d327082988018a25f56147d3b6d02f6c79ecc`。它不是历史 `f8859373...` 或 `P_reconstructed` 的重命名，历史结果不转移为本版本的结果。

## 来源与移植

原 head 的直接 parent 与它和新基线的 merge-base 均为 `8d77df617e85687567e9529fbc5520f793783e78`；原始累积差异只有一个提交，涉及五个文件。`source/` 保留仓库相对路径，`implementation.patch` 以共同基线为旧文件。补丁 SHA256 和每个源文件 SHA256 位于 `mechanism.json`。

三个已有文件在原 parent 和新基线字节相同，直接保留 PR head；新集成测试按原 head 复制。只有 `merge_insert.rs` 需要三方合并：以新基线为 current、原 parent 为 base、原 head 为 other，`git merge-file -p` 返回 0，没有冲突，也没有人工兼容修改。新基线已有的 source/target 条件 schema、nullable 修正、按动作决定旧列填充、deferred condition、lineage 和 writer 路由均保留。没有把旧整文件覆盖到新基线。

原 parent 的 `merge_insert.rs` blob 在本地 partial clone 中缺失。通过 GitHub Git Blob API 读取 `ba83ae7a072ba762eacd90b0fa1395a91b23fa91`，验证 Git blob SHA1 后使用；其余文件从 `git show` 读取。未写入原仓库 `.git`。

已读取 `review/9505-deferred-merge-payload` 的 README/IMPORT，以及原调查分支的统一设计与 ECS 任务书。它们用于理解历史候选边界，不把其中待验证目标写成本次已经完成的结果。

## 保留的核心机制

- **非索引 join：** 改成 `source JOIN target`，同步反转 Left/Right 的语义映射；保留 Inner/Full。MergeBudget 关闭 join reordering、join repartition 和 RoundRobin repartition，目标是 source build、target 单路 probe；扫描内部解码仍可并行。没有加入 native 多输出扫描。
- **pool：** 使用 `get_session_context(use_spilling=true)`；真实 v2 execute 使用规划时同一 session 的 task context。`LANCE_BYPASS_SPILLING` 仍可绕过限制。P 原版 analyze 只另外创建同配置 bounded context，并不共享规划 context 的实例，这一点原样保留。
- **scan：** I/O 目标为 `min(max(pool/4, 16 MiB), configured I/O bytes)`；用该值除以 `max(1,min(compute CPUs, session target partitions))` 得到每批估计字节，再除以全表 data-file bytes / physical rows 的平均磁盘行宽。只有计算行数小于 `BATCH_SIZE_FALLBACK` 才覆盖 scanner 行数；缺少 manifest rows/file sizes 时保持默认。不是实际投影 Arrow 宽度，也不是分配准入。
- **遗漏旧值：** 继续使用原 early fill，没有 D 的 late payload。P 的收益同时包含选边、probe 并行/队列、scan 预算与 pool 改动，不能仅归因于选边。

对应代码：`merge_insert.rs` 的 `MergeBudget`（约 1196 行）、`scan_io_bytes`（1253）、`target_scan_batch_rows`（1263）、`create_plan_join_type`（2600）、`create_plan_in`（2718）和 `execute_uncommitted_v2`（2891）。

## 完整保留的外围改动

索引路径的未索引 fragment scan 使用同样 I/O/rows 预算；Union 后改用 Coalesce，避免 RoundRobinBatch(1) 的重批处理。索引 join 从 Full 改为允许插入时 Left、否则 Inner，不再输出无需处理的 target-only 行。其执行仍调用原 `execute_plan(use_spilling=true)`，不是沿用临时 scan budget 的 context 实例。

旧 full-table stream 路径与列补丁排序均使用 `MergeBudget(..., Some(1))`。列排序只用一个 partition，保留既有 25 MiB input batch cap；名义 pool 大小先按默认 options 解析，再覆盖 session partition 数。Python 改动仅更新计划文档与测试断言，没有新公开参数。原 PR 的独立内存集成测试完整保留。

这些外围改动不属于本轮非索引 RewriteRows 计时格的覆盖范围；该格成功不能证明已验证索引路径或列重写路径，也不能宣称 D 替代它们。

## 边界与验证状态

固定 source build 可能让大 source / 小 target 在 pool 内失败；此失败必须作为结果保存。扫描与 decode 不向 DF pool 完整登记，磁盘均值可能受压缩、偏斜、大单值、投影变化影响，不能声称 RSS 硬上界。probe 单路可能损失吞吐。

原集成测试的多个连续 upsert 使用相同 NEW_BYTE；只有首次操作改变这些值，后续步骤仍检查更新计数与内容，但不能当成每次都改变值的性能证据。本次不改原测试来改善对照结果。

本地仅完成源码静态审计、无冲突三方合并，以及在 `git show 0a0d327` 文件树上执行 `git apply --check`。没有 build、测试、lint、SSH 或性能测量；没有修改主工作树或冻结 K。构建和真实计划/结果验证由主任务后续执行。
