> Historical report. Status statements describe the stage when this report was written. See the [review index](../README.md) for the published branch context. Only links were adapted below. The [original report](../evidence/independent-review-first.md) remains byte-identical.

# 首轮独立审查

本轮确认一个应修复的诊断错误：新增 replayable factory 发生失败时，`analyze_plan` 会返回看似成功的零行计划。匹配构建的性能比较和完整项目检查仍在运行或待运行，因此候选尚不满足交付标准。

审查对象固定为 base `4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9` 上的 `pre-phase1.patch`；已核对 SHA256 为 `dca79bf7508e03703a304ca64e6fd1b2879de7e5f79dd5050b15601641e9c2c1`，暂存 tree 为 `311e548ea0e2be0d17922f20f29aadd6feb5c560`。没有读取 Phase 1、排除的旧 Draft PR、其实现或衍生报告。本审查从任务、Issue #7895、背景 PR #7368 原始 review、官方 base、固定补丁、原始测试记录和测量脚本出发；实现者的结论未作为正确性证据。

## 代码与输入契约

**[P2] `analyze_plan_replayable` 吞掉 factory、schema 和读取异常。** `python/src/dataset.rs:623` 将新的 lazy provider 交给已有 `analyze_plan_provider`。共用 `rust/lance-datafusion/src/exec.rs:815` 使用 `while (stream.next().await).is_some() {}`，没有检查流内的 `Err`。独立实测中，同一 `WriteSource` 的 factory 抛错、reader metadata 不符、第一批读取抛错都会让 `execute` 抛出 `OSError`，而 `analyze_plan` 均返回 `output_rows=0` 的计划。诊断结果掩盖了来源失败，并与该方法的错误传播文档不符。

底层丢弃错误的行为已在 base 存在；本次新增 lazy factory 会把打开来源时的失败带入这条路径，不能把整个 helper 问题都归为本补丁引入。建议在共用 helper 中传播执行错误，或以同样可靠的局部方式保留错误传播；添加 factory/schema/batch 三类 `analyze_plan` 失败回归。不要通过提前打开 factory 后丢弃 reader 来绕过问题，这会改变生命周期并制造无用读取。重现脚本、原始结果和 stderr 分别为 `independent-review-analyze-error.py`、`independent-review-analyze-error.json`、`independent-review-analyze-error.stderr`，使用当前扩展和单 Tokio worker。

`coerce_source` 将分类和读取能力放在同一个 singledispatch 结果中。第三方能返回公开的 `WriteSource(schema, factory)`，Rust 实际调用 factory 并重新导入 Arrow reader；该接口不依赖 Lance 私有对象。这个描述对象具有当前需求依据。新增 Rust 部分复用 `StreamingTable`、`reader_to_stream` 和已有 `execute_provider`，没有新增核心重试框架。

原生 Lance scanner 保留已构造的 native scanner，并用 Python 配置快照限制自动重扫资格。表达式、过滤、搜索、显式乱序、排序和回调不因可重新调用 `to_reader` 就取得资格。Python 对新增 scanner 配置采用默认拒绝方式。稳定投影、limit/offset、显式 fragment 顺序及元数据保留有代码依据和实测支持。

Arrow Dataset 自动支持范围限于无隐藏 filter 的内置 memory/filesystem/union 类型；文件不可变性仍由调用方承担。opaque Arrow Scanner 自动回退合理：公开 API 不能判断它是否来自 one-shot `from_batches`。调用方可以用显式 `WriteSource` 承诺配置后的 Scanner 可重复读取。这是有说明、有回退测试的支持边界，不能在 PR 中简写成所有 Scanner 自动免缓冲。

`execute_uncommitted` 消费一次 reader，不添加 retry provider；`analyze_plan` 对 replayable 来源走与执行相同的 provider，但存在上述错误传播缺陷。materialized 和 one-shot 路径继续调用已有入口。factory 在阻塞线程上运行，避免占用 Tokio async worker；Rust 测试覆盖 factory 取消后返回的 reader 释放。reader schema 在 Python 和 Rust 边界包含 metadata 检查，执行路径的错误有上下文。单 worker 的实际重试记录支持新增回调路径不会因该测试场景而死锁，但不等于证明任意第三方 callback 都能被取消或安全阻塞。

## 已检查的验证

原始日志记录首轮 Python 定向测试 88 项、write 回归 116 项、MemWAL 回归 21 项、source doctest 1 项和 Rust provider 测试 4 项通过。当前 Arrow 25.0.1、Arrow 14.0.2、单 Tokio worker 记录均指向本轮扩展 SHA256 `63e42bdc2884c488248892631abeb03bfa2b7c525bd1c1e2a53310576800e6dd`。我读取了兼容性与冲突注入脚本，确认外部类型测试实际创建竞争提交并再次调用 factory，最终提交到 version 3。

缓冲检测器同时观测 `.tmp` 目录创建和 `spill.arrows` 删除；base 的 `spilling_table_provider` 在开始内存缓冲前无条件创建该目录。`controls/dev` 中 one-shot 和 baseline Lance/Arrow 输入能触发目录计数，即使 source 只有 256 字节且没有 spill 文件。candidate Lance/Arrow 在实际冲突下目录计数为零，one-shot/opaque Scanner 仍为一；重试版本和最终数据校验通过。因此这组证据能区分“未进入目标 replay 机制”和“数据太小而未落盘”。这些 DEV 时间不支持性能收益结论。

独立额外探针 `independent-review-probe.py` 已运行，结果为 `independent-review-probe.json`，stderr 为空。它使用上述本轮扩展，并验证：

1. Dataset 默认 columns、offset、limit、batch_size 与字段/Schema metadata 得到保留。
2. 第一次提交冲突时同时修改 source handle；真正第二次执行仍使用适配时固定的版本。
3. 三个 Lance fragments 逆序读取在重复扫描中保留 encounter order。
4. 三个 Arrow 文件的显式逆序及 metadata 在重复扫描中保留。

运行命令：在 `/workspace/lance-7895/python` 执行 `source /workspace/issue-7895-evidence/env.sh`，然后执行 `TOKIO_WORKER_THREADS=4 uv run --no-sync python /workspace/issue-7895-evidence/independent-review-probe.py`。探针只写一次性数据与仓库外证据，没有修改候选源码。

## 收尾必须补齐的事项

1. 修复或明确解决上述 `analyze_plan` 错误传播发现，补回归并重新审查改动。
2. 完成固定 baseline 与候选的匹配优化构建测量，覆盖无冲突与实际重试；保留原始重复样本、扩展 hash、实际执行计划和构建 profile。当前仅有 baseline 优化计划及 DEV 控制实验，不能判断收益、退化或将差异归因于 replay。
3. 完成规定的完整 Rust clippy 和 Python lint，并记录运行命令、结果及对应最终产物；当前审查不能把运行中/待运行的检查写成通过。
4. Phase 1 对照或后续审查产生的实质修改，需要针对最终 patch 复核并重跑受影响检查；本报告的结论只适用于上述固定快照。

补充低优先级文档建议：`coerce_source` 的 “Registration applies to all Python write entry points” 可缩成“接受 ReaderLike 的写入入口”；部分 API（例如 add_columns）还有 callable/dict 等更高优先级的自身语义，注册不应被理解成覆盖这些语义。`write_dataset` 的既有 `TODO add support for passing in LanceDataset and LanceScanner here` 已与可用转换路径不一致，可在本次统一 source 语义时删除。两者不构成本轮正确性阻塞项。
