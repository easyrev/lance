> Historical report. Status statements describe the stage when this report was written. See the [review index](../README.md) for the published branch context. Only links were adapted below. The [original report](../evidence/delivery-report.md) remains byte-identical.

推荐保留这一份内聚候选：用公开的实验性 `coerce_source` 注册接口统一 Python 输入转换，由 `WriteSource` 提供实际可调用的 reader factory。合格来源交给 Rust 已有 `TableProvider` 重试机制，每次执行创建新 reader，跳过一次性来源的 replay 缓冲。无法确认值与顺序稳定的来源继续使用安全回放路径。

候选实现、回归测试、独立审查修复、最终机制对照和匹配性能测量均已完成。独立证据复核未发现新增阻断问题。仍需维护者确认实验接口和下述性能取舍；完整测试套件与远端 CI 未运行。本轮没有执行 push、远端 PR/评论修改或其他发布操作。

**支持范围与行为。** 判断条件同时涉及 schema、版本、值和顺序，不能只看是否还能调用一次 `to_reader()`。

| 输入 | 候选行为 | 必要边界 |
| --- | --- | --- |
| `LanceDataset`、合格 `LanceScanner` | 保留已创建的原生 scanner，固定来源版本和扫描设置，自动重扫 | 只接受已确认保持值与顺序的配置；直接投影、limit/offset、批次设置和显式 fragment 顺序等得到保留 |
| 内置 Arrow `InMemoryDataset`、`FileSystemDataset` 及其 union | 无隐藏 filter 时自动重扫，保留原 schema 与碎片顺序 | 文件内容在操作期间必须不变；不把自定义 Dataset 子类自动视为稳定来源 |
| 不透明 Arrow Scanner、filtered Dataset、动态或无序 Lance scan | 保留 streaming 路径；启用冲突重试时使用原有 replay 缓冲 | Arrow `Scanner.from_batches` 可能只能读取一次；随机计算、搜索和排序等不能仅凭类型证明可重复性 |
| 第三方类型、调用方明确保证稳定的配置后 Scanner | 注册函数返回 `WriteSource(schema, open_reader)`，Rust 实际调用 factory | 每次返回新 reader，schema 含 metadata、值和 encounter order 均相同；来源不可变或固定版本；支持工作线程及可能重叠的调用 |
| materialized、one-shot 和原有可转换输入 | 保留原策略，避免两个分类列表继续漂移 | HF/Pydantic 原有路径保留；延迟加载不会覆盖第三方已注册适配器；自定义 Scanner 仍只需原有 `to_reader()` 契约 |

`execute` 与 `analyze_plan(data)` 使用一致的来源策略。普通写入与 `execute_uncommitted` 只消费一次 reader；后者不提交、不更新原 dataset。`explain_plan(schema)` 仍是 schema-only 的 streaming 形状说明。注册不会覆盖各入口自身的 callable、dict 或其他专用语义。factory 的返回值和完整 schema 在 Python/Rust 边界校验；取消不能强制中断尚未返回的 Python callback，reader 在 callback 返回并结束执行后释放。

**代码与版本。** 当前固定补丁只包含七个生产/测试文件；实验脚本、原始结果和本文均在仓库外，不默认加入 PR。

| 对象 | 标识 |
| --- | --- |
| 官方 upstream base | `4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9` |
| 隔离工作树与分支 | `/workspace/lance-7895`，`codex/issue-7895-independent` |
| Phase 1 对照前候选 | [pre-phase1.patch](../evidence/pre-phase1.patch)，SHA256 `dca79bf7508e03703a304ca64e6fd1b2879de7e5f79dd5050b15601641e9c2c1`；tree `311e548ea0e2be0d17922f20f29aadd6feb5c560` |
| 审查修订后的冻结候选 | [review-phase1-final.patch](../evidence/review-phase1-final.patch)，SHA256 `9694eb0eaf38d30a9ea87556163b4403ea88d7a4b54e0da6d8e8907306658ed5`；tree `266fe35ffdb06144ba73a255ef8d51e13ba32516` |
| 最终本地 commit | `26632629ca162cdbfd82dabad1d80e3e6c92b364`；已核对其 tree 及相对 base 的 binary patch SHA256 均与上述冻结候选相同 |
| 最终定向验证所用扩展 | `/workspace/lance-7895/python/python/lance/lance.abi3.so`，SHA256 `b4b1c1da690158d29e53ee79e8a57138b934054d16961c8e6ec25f63db4280d4` |

[候选审查包](../candidate-review-bundle.tar.gz) 汇集补丁、报告、脚本、原始结果和校验清单。完整二进制及测试数据留在工作区，未重复打包。

建议按以下顺序阅读代码：

1. [WriteSource 与注册接口](https://github.com/easyrev/lance/blob/26632629ca162cdbfd82dabad1d80e3e6c92b364/python/python/lance/types.py#L64)：统一能力描述、类型适配、schema 校验和公开契约。
2. [merge 执行入口](https://github.com/easyrev/lance/blob/26632629ca162cdbfd82dabad1d80e3e6c92b364/python/python/lance/dataset.py#L379) 与 [Lance 资格判断](https://github.com/easyrev/lance/blob/26632629ca162cdbfd82dabad1d80e3e6c92b364/python/python/lance/dataset.py#L8845)：保留源语义并选择执行路径。
3. [Rust reader factory provider](https://github.com/easyrev/lance/blob/26632629ca162cdbfd82dabad1d80e3e6c92b364/python/src/dataset/replayable.rs#L23) 与 [Python 绑定](https://github.com/easyrev/lance/blob/26632629ca162cdbfd82dabad1d80e3e6c92b364/python/src/dataset.rs#L519)：复用 `StreamingTable`，在阻塞线程打开 Python reader，避免占住 Tokio worker。
4. [共享 analyze helper 修复](https://github.com/easyrev/lance/blob/26632629ca162cdbfd82dabad1d80e3e6c92b364/rust/lance-datafusion/src/exec.rs#L778)：传播流内错误，并为 `AnalyzeExec` 使用正确的两列报告 schema。
5. [真实冲突矩阵](https://github.com/easyrev/lance/blob/26632629ca162cdbfd82dabad1d80e3e6c92b364/python/python/tests/test_dataset.py#L3879)、[动态值回放](https://github.com/easyrev/lance/blob/26632629ca162cdbfd82dabad1d80e3e6c92b364/python/python/tests/test_dataset.py#L4127) 和 [异常矩阵](https://github.com/easyrev/lance/blob/26632629ca162cdbfd82dabad1d80e3e6c92b364/python/python/tests/test_dataset.py#L4219)。

**已验证的结果。** 下表的最终 Python 与 provider 结果均来自冻结候选及上述本轮重建扩展。它们不引用其他工作树的二进制或旧阶段通过记录。

| 验证 | 结果与证据 |
| --- | --- |
| 来源、merge、原有输入与 metadata 定向回归 | **106 passed**：[python-provider.log](../evidence/review-final/python-provider.log) |
| fragment、UDF、JSON、MemWAL 回归 | **137 passed**：[python-write-regressions.log](../evidence/review-final/python-write-regressions.log) |
| 公开来源接口 doctest | **1 passed**：[python-doctest.log](../evidence/review-final/python-doctest.log) |
| Rust factory 延迟调用、重复执行、错误、metadata、取消后释放 | **4 passed**：[provider-tests.log](../evidence/review-final/provider-tests.log) |
| 共享 analyze helper 的 context 成功与失败路径 | **1 passed**：[root-core-tests.log](../evidence/root-core-tests.log) |
| Python/绑定规定检查 | `uv run --no-sync make lint` 通过；Ruff 通过，Pyright 0 errors，14 条第三方依赖 warning：[lint-full.log](../evidence/review-final/lint-full.log) |
| Rust 项目检查 | 绑定 `cargo clippy --all --tests --benches -- -D warnings` 与根 workspace 的同范围 CI profile 检查通过：[绑定日志](../evidence/review-final/clippy-all.log)、[根 workspace 日志](../evidence/root-workspace-clippy.log) |
| PyArrow 兼容与运行时 | Python 3.12.14 下，PyArrow **25.0.1**、最低主版本的 **14.0.2**，以及 **单 Tokio worker** 的嵌套 factory/真实重试均通过：[当前版本](../evidence/review-final/compatibility-current.json)、[Arrow 14](../evidence/review-final/compatibility-arrow14.json)、[单 worker](../evidence/review-final/compatibility-single-worker.json) |

真实重试覆盖九种来源和两种竞争写入。竞争 upsert 同时重写旧行并插入一个源中的键；最终无重复键，插入/更新统计随目标刷新而变化。第三方 factory 在真实冲突后再次调用。版本、metadata、默认扫描配置、逆序碎片读取和错误后的无提交行为均有定向断言。随机计算来源只读取一次，重试结果与首次实际观测值一致。零重试负对照返回 `Too many concurrent writers`。

运行入口为 [run-review-fix-validation.sh](../evidence/run-review-fix-validation.sh)：在项目 `python/` 目录加载 [env.sh](../evidence/env.sh)，设置一个新的 `VALIDATION_OUTPUT` 目录后执行，避免覆盖原始日志。该脚本包含精确测试选择、兼容环境和 lint 命令。共享 Rust helper 检查命令在 [run-root-rust-validation.sh](../evidence/run-root-rust-validation.sh)。扩展路径、版本和 hash 在 [provenance.json](../evidence/review-final/provenance.json)。

**缓冲机制证据与性能边界。** 外部 `LD_PRELOAD` 探针同时记录 replay 临时目录创建与 spill 文件删除时的大小。当前实现进入 replay 缓冲前会创建目录，因此只看有没有磁盘文件不足以判断有没有缓冲。校准中的 **256 B one-shot 输入创建一个 replay 目录、没有 spill 文件**；materialized 对照两个计数均为零。约 132 MiB 的基线输入触发一个目录及一个 **138,518,792 B** spill 文件。调用栈解析到 `TempDir::try_new`，并与 replay 源码调用对应，证明探针能够捕获目标行为。

首轮候选 DEV 实测中，Lance/Arrow Dataset 在真实冲突下 replay 目录计数为零；one-shot 与不透明 Scanner 仍为一，数据与版本断言通过。证据为 [校准摘要](../evidence/calibration-summary.json)、[调用栈](../evidence/calibration-logs/oneshot-stack-symbols.txt) 和 [14 项机制对照](../evidence/controls/dev/summary.json)。这些观测支持“没有进入目标 replay 缓冲”，不能单独证明速度、总内存或总 I/O 改善。该 DEV 对照早于共享 analyze helper 修订；最终优化产物已完成下述独立复跑。

最终匹配优化扩展的 **14 项机制对照全部通过**：[final controls](../evidence/controls/final/summary.json)。120 次正式测量中，合格 Lance/Arrow 输入的 replay 目录计数始终从基线的 1 变为候选的 0；opaque Scanner 仍为 1。最终候选扩展 SHA256 为 `852dee3bca568063563fc9b66d2f13904b56cc796116fcdd27e5cefe71fa4114`，基线为 `cdfc0093f978a131a608fec65ac15f1526655832a3b571ca7b01e4ba1a53c6b6`。两份构建使用同一 `release-with-debug` 配置；56 个 Python 文件分别与固定提交逐一匹配，移除调试信息前后的 28 个加载段一致。完整记录见 [产物索引](../evidence/native-snapshots.json)。最终优化扩展的兼容性与单 worker 真实重试也重新通过。

性能矩阵包含 **120 次测量**：1.125/132 MiB 两档输入，Lance/Arrow/Scanner 三种来源，无实际冲突/真实重试，两份产物，各五次重复。所有样本均检查完整数据、版本、提交 hook 序列及 merge 统计，原始结果全部保留。

| 实测场景 | 基线 → 候选 | 可支持的结论 |
| --- | --- | --- |
| 132 MiB，Lance，无冲突 | 中位 230.82 → 218.17 ms；RSS 543.2 → 434.9 MiB；spill 132.10 → 0 MiB | 此负载省去 replay 临时文件，耗时和进程峰值内存均下降 |
| 132 MiB，Arrow，无冲突 | 中位 201.76 → 193.26 ms；RSS 747.3 → 631.9 MiB；spill 132.11 → 0 MiB | 此负载同样改善，不能外推到全部来源与重试条件 |
| 1.125 MiB，Lance，无冲突 | 主矩阵中位 9.28 → 11.93 ms；另做十对无探针复测为 11.20 → 11.95 ms | 未显示小输入延迟收益；首轮 +2.65 ms 的幅度不稳定，复测仍高约 0.75 ms，区间重叠 |
| 132 MiB，Lance，真实重试 | 总 wall 中位 813.29 → 982.04 ms；CPU 685.11 → 732.02 ms；RSS 570.1 → 609.1 MiB | spill 消失，但 CPU 与 RSS 仍有实测代价；不能声称重试全面更快、更省内存 |
| 132 MiB，Arrow，真实重试 | 总 wall 中位 390.78 → 834.62 ms；CPU 649.66 → 648.48 ms | wall 差异伴随宽且重叠的随机等待区间，不能解释为处理成本翻倍 |

独立脚本审查确认重试包含随机退避，因此新增首次 commit 前耗时与 CPU 观测，并保留全部总耗时；成对实验没有共享随机等待槽。六组实际计划的算子、join 配置、源 batch/row 数及 target build 行数匹配。Scanner 回退也存在耗时波动，作为对照单列。源码可以确认候选在实际重试时重新扫描来源；它支持解释重读这一代价，但不足以证明全部测量差值只来自重读。

完整范围、所有退化、中位数及 min/max、CPU/RSS/临时存储/I/O 原始量见 [性能报告](performance-report.md)、[全部比较](../evidence/performance-comparisons.json) 和 [无探针复测](../evidence/no-probe-followup-summary.json)。无探针复测独立保留，未替换首轮样本。

测量脚本和复现方式在 [测量说明](README.md)。设计采用本地暖缓存、相同来源文件与线程设置、新进程、交替次序和全部重复样本保留。`max_rss` 包含进程初始化，不等于 replay 独占内存；spill 删除时文件大小不等于物理磁盘写入量。源码推断支持省去一份来源缓冲，性能结论只能取自最终测量，不能外推到冷缓存或云存储。

**独立审查与来源隔离。** 首轮审查者使用独立上下文，从任务、Issue、背景 PR review、官方 base、固定 patch 与原始证据开始。它发现 `analyze_plan` 会吞掉 factory/schema/batch 错误，返回看似成功的零行报告。共用 helper 的丢错行为原已存在，本次 lazy factory 使打开来源的失败也进入该路径。修复同时纠正 `AnalyzeExec` 报告 schema；只传播错误而不修 schema，会暴露正常分析报告构造失败。中间失败日志保留，没有当作最终通过结果。

独立修订探针已在最终源码对应的 DEV 扩展 `b4b1c1da690158d29e53ee79e8a57138b934054d16961c8e6ec25f63db4280d4` 下、单 Tokio worker 环境重新验证：六种分析错误正确抛出，三种来源的正常 merge 分析及普通 scanner 分析成功，均不提交 dataset 版本。首轮 P2 已关闭。参见 [首轮审查](independent-review-first.md)、[修订审查](independent-review-revision.md) 与 [最终独立探针结果](../evidence/independent-review-revision-probe.json)。

已按门槛先保存独立候选、完成首轮定向验证和独立审查，之后才读取指定 Phase 1 报告。UTC 2026-10-11 **13:14** 保存快照、**13:20** 完成首轮审查、**13:23** 读取对照。对照唯一引起的实质修改是扩展竞争 upsert 测试，验证刷新后的新匹配键；没有据此改变生产方案，也没有继承旧测试通过记录。详见 [Phase 1 对照](phase1-comparison.md) 与 [独立来源合同](source-contracts.md)。全程未读取排除对象的 diff、正文、讨论、实现或衍生报告；官方 Issue 自动展示的链接元数据接触另有记录，未用于设计。

**仍需社区确认的实际取舍。** 建议在这一候选中保留以下选择，交由维护者 review，而非因此停止交付：

- 推荐将 `coerce_source` / `WriteSource` 放在 `lance.types`，标为实验性，不增加顶层重导出。第三方真实重试已验证这套契约可执行，但尚未覆盖更广泛的外部集成。仍成立的备选是直接承诺稳定 API；代价是现在就固定 reader 生命周期、并发调用和重读契约。请维护者在 review 中确认名称、位置及实验性状态。

- 推荐对已确认稳定的内置来源默认启用重扫，并保留 `WriteSource.from_reader(source.to_reader())` 这一显式回放选择。验证显示大输入可省去约 132 MiB 临时文件，但小 Lance 延迟及大 Lance 实际重试 CPU/RSS 有成本。仍成立的备选是默认保留 replay、仅允许显式工厂免缓冲；它保留扩展能力，却失去普通 Dataset 输入的自动收益。维护者需确认是否接受当前默认策略的实测取舍；本候选已采用前者。

独立最终审查与计算记录见 [最终性能证据审查](independent-performance-final.md)。审查者重新核对 120 个主样本、14 项控制、20 次无探针补测、两份 native hash 和两份 Python 包的全部 56 个文件，并重算中位数及范围。

其余边界已经选定并实现，无需用户补做技术选型。当前未运行完整 Python 测试套件、整个 Rust workspace 测试套件、所有受支持 Python 版本和远端 CI；没有远端存储性能证据。32 GiB 磁盘限制曾导致构建安装空间不足，已通过本轮缓存整理与重建完成现列验证，失败和恢复日志均保留。最终性能证据已由独立审查者核对，未发现新增阻断问题；结论限定于本地暖缓存和已测来源。恢复入口为 [RECOVERY.md](RECOVERY.md)；英文 PR 标题与正文见 [待发布草稿](../evidence/pr-draft.txt)，没有执行发布。
