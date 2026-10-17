# Lance #9505 根因与设计记录

## 验证对象

研究基于上游 main `dc53d5d174af62c49ddd98d1024a64488c1e4404`。2026-10-18 再次查询 GitHub，main 和 #10077 head 均未变化。#10077 head 为 `9e1ebc2e816a7195b56757ebe269e74989fc30c7`，用于比较的是它与上述 main 的干净合并结果 `f8859373d5022eedea239db2fcfd68713a423762`。PR 与 main 的实际 merge-base 是 `8d77df617e85687567e9529fbc5520f793783e78`；GitHub 返回的目标分支 SHA 不能代替 merge-base。

全部云端工作位于 `/mnt/lance/issue-9505`，使用独立 bare repository、worktree、虚拟环境和复制的编译缓存。原有 #7895/#9617 checkout 与 target 目录未修改。未创建 GitHub PR，未发表上游评论。

## 问题报告与 workload 证据

| 证据 | 已知内容 | 能支持的判断 |
| --- | --- | --- |
| [#9505 原始报告](https://github.com/lance-format/lance/issues/9505) | 约 81.6M 行、494 fragments、44 列；100 行 source，仅 key 和两个替换字段；SDK 未暴露 write_mode，调用者用 use_index=false 获得 RewriteRows；报告 110 GiB cgroup OOM、49 秒 | 小 source、大 target、稀疏部分列更新是本修复的主要场景。报告没有提供全部字段类型或可直接重放的数据集 |
| 当前 main 源码及 [#7368](https://github.com/lance-format/lance/pull/7368) | materialized 输入进入 MemTable，reader 进入无统计的 StreamingTable；默认重试 spill 仍不发布统计 | “小 source”不能只看行数；API 输入形式直接改变计划。当前 main 已经能正确规划普通 materialized 小输入 |
| 仓库 merge_insert benchmark | 包含 10M 窄表、1M 宽表/向量、10M 行/10K fragments；source 多为 materialized，规模 1K/10K/100K | 必须保留已工作的 materialized 路径；这些数据不能证明所有生产输入都很小 |
| [#10077](https://github.com/lance-format/lance/pull/10077) 测试 | 200/400 行、每行 5 MiB binary，25 行 source 带 1/10 MiB binary；同时覆盖 indexed fallback 和 column patch | 是有效的宽行压力边界，但与原报告的 80M 行场景不同 |
| 本地反向规模测试 | 100K target，3M 行全列 source，更新加插入 | 防止 source-build 对合法大输入造成回退；不据此推断该场景的生产占比 |

报告中的 110 GiB、49 秒、indexed 23K keys/28 秒均为报告者的数据。本研究使用固定随机种子的合成数据，实际测量见结果表和原始 JSON，不将两组数据混用。

## 调用链与直接根因

```text
Python MergeInsertBuilder.execute
  -> _coerce_reader / _is_materialized
  -> PyO3 execute_batches 或 execute
  -> Rust execute_batches(MemTable) 或 execute_reader/execute
  -> stream_source_to_provider
  -> execute_inner 重试循环
  -> execute_uncommitted_impl
  -> 非索引 execute_uncommitted_v2 / create_plan
  -> target JOIN source
  -> DataFusion JoinSelection
  -> HashJoinExec 左侧 build
  -> FullSchemaMergeInsertExec / InPlaceMergeInsertExec
```

main 的 reader 源没有行数和字节统计。目标大于 DataFusion 的 CollectLeft 阈值时，优化器不能通过两侧大小比较换边，保留 target build。HashJoin 保存 build batches、建立哈希表，并在拼接过程中同时持有旧批次和新分配的数组。目标规模随之成为峰值内存的主要决定因素。

部分列 RewriteRows 必须取得 source 没有提供的旧字段。实测 44 列固定宽度 fixture 中，target scan 携带 key 和 41 个遗漏字段，共 42 个数据字段，再加 row ID/address；两个被替换字段仅来自 source。不能把原报告“扫描全部 44 列”的概括直接当成当前 main 的实际投影。

4M target/100 source 的诊断计划显示：main 的 build_input_rows 为 4M，build_mem_used 约 1.57 GB；materialized source 的计划为 CollectLeft，build_input_rows 100，build_mem_used 约 4.70 KB。两种计划均扫描 4M target 行，故收益不能解释为跳过了目标数据。

main 规划使用 `SessionContext::new()`，实际执行使用 `TaskContext::default()`，均没有启用 Lance 的有界执行池。DataFusion 54.1 的 HashJoin 在 reservation 不足时返回 ResourcesExhausted，**没有 hash join 落盘实现**。`use_spilling=true` 为支持 spill 的算子提供环境，并不使所有算子都能 spill。

执行池也不等于进程 RSS 上限。source 构造、scan 解码、部分 batch 合并和 writer 分配不全由 HashJoin reservation 覆盖。DataFusion 54.1 的 `joins/hash_join/exec.rs` 在普通 hash-map build 路径先为输入 batches 和哈希表预留内存，再于约第 2014 行执行 `concat_batches`，此处没有独立预留第二份完整拼接内存；这不代表该文件所有 concat 路径都没有 reservation。测试必须同时观察执行池错误、进程 RSS 和 cgroup OOM。本研究没有通过 heap profiler 把宽列 OOM 的每一份分配精确归因。

可从固定版本源码复查调用关系：[Python 输入分派](https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/python/python/lance/dataset.py#L379)、[PyO3 入口](https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/python/src/dataset.rs#L474)、[Rust provider 与 retry 入口](https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance/src/dataset/write/merge_insert.rs#L2356)、[非索引建计划](https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance/src/dataset/write/merge_insert.rs#L2600)、[Lance 执行上下文](https://github.com/lance-format/lance/blob/dc53d5d174af62c49ddd98d1024a64488c1e4404/rust/lance-datafusion/src/exec.rs#L327)。

## 维护者意见及历史方案

[#9505 的维护者回复](https://github.com/lance-format/lance/issues/9505#issuecomment-5798439622)明确希望 source 提供统计；[#10077 review](https://github.com/lance-format/lance/pull/10077#pullrequestreview-5552517026)要求解释宽度估计，并指出 MemTable 可以从实际 batches 提供统计。另一个 [blocking review](https://github.com/lance-format/lance/pull/10077#discussion_r4298410759)要求给禁用优化和并行度的改动提供 benchmark，而非仅凭计划形状判断性能。

[#7382](https://github.com/lance-format/lance/pull/7382)已提出 source-first，仍然 open；维护者曾暂时接受，但更倾向 #7368 的统计方案，并明确提到大 source、窄 target keys 的反向情形。[#7719](https://github.com/lance-format/lance/pull/7719)已有执行内存上限方向的未合并工作。[#8423](https://github.com/lance-format/lance/pull/8423)明确了 write_mode，应区分 RewriteRows 与 RewriteColumns 的读写成本。

已合并的 [#8772](https://github.com/lance-format/lance/pull/8772)修正了 analyze_plan 与 execute 的输入分派不一致。本补丁继续遵守这项契约：两者使用相同的 source 准备过程，schema-only explain 则仍然无法获知实际数据统计。

[#7363](https://github.com/lance-format/lance/issues/7363)记录过 late materialization 的尝试：join 打乱地址后，take 失去顺序读取效率，需要足够强的选择性才有收益。这是历史实验给出的风险，不代表 late materialization 在本报告的稀疏更新上一定更慢。本研究没有实现该方案，因此不报告其速度或内存指标。

## 方案比较

| 方案 | 正确性与资源行为 | 性能及维护成本 | 本研究判断 |
| --- | --- | --- | --- |
| 仅启用执行池 | 不改变错误的 build 选择；已记账部分超限时返回错误 | 改动小，但不能让原始小 source 更新成功；仍非进程硬上限 | 只能作为必要的失败保护之一 |
| source-first，保留优化器 | JoinType 可正确反转，但未知大 source 会被构建；已知小 target 仍可能触发换边 | 实验 A 在正向规模降内存，但反向 streaming 在 1 GiB 池失败，64M 正向仍需 15.33 秒 | 不作为最终修复 |
| 永久强制 source-build / 单 probe 分区 | 规避 target build；大 source 仍必须放入构建内存 | #10077 正向最快，反向场景明显回退；还涉及 scan budget、indexed fallback、column patch sort | 有价值的性能数据，不能据此直接接受全部范围 |
| 完整 drain 任意 source 后统计 | 能获知真实总量，需要保存整个输入用于执行/重试 | 大输入增加启动屏障、磁盘读写或驻留内存 | 不采用无界预读 |
| 有界预读，EOF 后发布统计 | 小流获得精确统计；超界则保留原前缀和流顺序；不把样本当总量 | 保留原优化器和大输入策略；增加有限的启动等待，解决范围明确 | 最终候选 B；回归和 benchmark 结果见验证报告 |
| late materialization | 可仅构建 key/row address，再读取需要的旧值 | 涉及 unmatched/NULL/投影/行地址与 take，稠密更新可能增加随机 I/O | 本次不扩展到该设计，收益仍待单独实测 |

Lance 对变长字段的部分 scan 字节统计来自解码器宽度种子，而非实际 payload 长度。400×5 MiB target 看起来可能比 25×10 MiB source 小。仅补齐 source 统计不能保证这类错误 target 宽度估计得到纠正；这与原报告中完全缺失 source 统计是两种不同条件。

## 实验 B 的职责边界

仅在将进入非索引 create_plan 的流入口预读。字节上限复用现有 retry buffer 的 100 MiB 预算，行数上限沿用 DataFusion 的 128 Ki 行阈值；超过任何一项立即停止继续拉取。只有遇到 EOF 才改用 MemTable。这些上限限制预读，不强制 CollectLeft：例如 100K 行、三个 int64 字段约 2.4 MB，超过 DataFusion 的 1 MiB collected-byte 阈值，但其真实统计仍能帮助 partitioned join 选择较小的构建侧。单个调用者 batch 可以超过预读阈值，前缀会连同原 stream 继续向下传递，因此该阈值不是调用者 batch 大小或进程 RSS 的硬上限。

FirstSeen 必须先按原 source 分区顺序确定胜出行。若输入已有精确的小表统计，则完成这次有界去重并用 MemTable 保留去重后的统计；大输入继续使用原 streaming 去重。关闭 retry spilling 时仍保留 fail-fast 契约，即使小 source 已经成为可重扫的 MemTable，也不擅自启用重试。

预读会提前消费 source，因此必须保留已有的输入前校验。现有 invalid lineage budget 回归暴露了顺序变化，最终实现先验证 write sink 和行 lineage budget，再开始第一次 source poll。

JoinType 映射、matched/unmatched 表达式、source sentinel、NULL 判定和 write sink 均沿用 main。实际非索引执行、规划和 analyze 使用 Lance 有界上下文。indexed join、扫描器、解码器、column patch sort、公开参数及文件格式均不修改。

实测该方案使小 streaming source 达到 main 已有的 materialized source 计划。它不承诺任意大小 reader 都能提供统计，也不承诺 scan/writer/超大单元格受到全进程统一内存管理。完整结果、反例和提交判断见 [REPORT.md](REPORT.md)。
