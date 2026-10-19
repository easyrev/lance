# 本轮测试覆盖审计与最小补充命令

本审计只读取统一基线 `0a0d327082988018a25f56147d3b6d02f6c79ecc` 的 P/DP ports、现有 Rust/Python 测试及本轮测试 driver；没有运行测试、构建、SSH 或修改冻结源码。以下“覆盖”指测试实际构造的路径及断言，不表示本轮已通过。执行结果、测试二进制与候选 patch 的对应关系须以主任务日志为准。

## 1. 最小新增执行：P、DP 各跑一个 integration target

主任务已排队的 DB/DP 命令是 `cargo test -p lance --lib dataset::write::merge_insert --profile release-with-debug --locked -- --test-threads=4`，包含 merge 模块及其子模块中的现有 indexed/Columns、D condition、DP 组合和 retry 测试；`--lib` **不包含**新增的 integration target。因此最小新增不是重复挑一组 lib 测试，而是 P、DP 各跑一次下列完整文件。

在主任务已准备好对应 port 的独立 tests checkout、加载项目 Rust 环境且设置对应 `CARGO_TARGET_DIR` 后运行：

```sh
cargo test -p lance --test merge_insert_memory_bound --profile release-with-debug --locked -- --test-threads=1
```

target 是 `merge_insert_memory_bound`，文件中唯一的 test 是 `test_partial_upsert_into_wide_rows_fits_pool`。不加 name filter，避免筛到零个测试而误报通过。P 和 DP 不能共用未重新编译的同一二进制；可以分别复用各自 tests target 的依赖产物。该文件改进程级环境变量且安装全局 allocator，必须保持独立 binary；`--test-threads=1` 明确这个要求。[唯一测试及全局环境](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/tests/merge_insert_memory_bound.rs:167)

它是完整文件可直接执行的单一 integration test，但不应称为轻量快速单测：需要构造 25 fragments、200 行 × 1 MiB 的随机 Binary payload，并多次全表 readback。当前静态审计不能保证耗时或峰值；应在性能测量开始前独立执行，避免与构建、测试和基准交叠。无需为本轮技术结论增加 workspace Clippy 或重复全工作区测试。

若 DP 完整 lib suite 无法完成，不能用这个 integration 代替其组合语义验证。至少应补下列已有 filter；本轮已排队完整 suite 时无需再运行：

```sh
cargo test -p lance --lib test_partial_merge_conditions_inserts_deletes_and_duplicates --profile release-with-debug --locked
cargo test -p lance --lib test_partial_merge_retry_refreshes_payload_and_row_address --profile release-with-debug --locked
cargo test -p lance --lib dataset::write::merge_insert::exec::condition::tests --profile release-with-debug --locked
cargo test -p lance --lib test_unknown_wide_source_exhausts_fixed_source_build_pool --profile release-with-debug --locked
```

上述备用命令不是新增待办，完整 suite 已包含它们。condition 软分块的突增值补充用例由本轮 `tests/late-jump.patch` 加入独立测试快照，也在相同 merge 模块 filter 内。它与生产 ports 的差异为测试代码，应继续单独记录 test snapshot；不能把测试快照 hash 当成基准二进制源身份。

## 2. P integration 实际验证什么

同一个 dataset、同一组更新 keys `[40, 41, 42, 43]`、同一 `NEW_BYTE=0x42` 依次运行四阶段。source 提供 `key,payload`，只遗漏 `tag`；开启 UpdateAll，source-only 为 DoNothing。最初只给首个 fragment 建 key index，随后追加其余 24 fragments。[source 及执行窗口](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/tests/merge_insert_memory_bound.rs:101)

| 阶段 | 路由及实际覆盖 | 内存断言 | 正确性断言的范围 |
| --- | --- | --- | --- |
| Auto，部分 index | 未命中 index 的 appended fragments 进入 indexed fallback scan，执行 column patch；DoNothing 对应 indexed Inner join | 本次 merge 的全局 Rust allocator 计数峰值增长 `<128 MiB` | stats 更新 4/插入 0；200 行、payload 长度均 1 MiB、tag 均 old、恰有 4 个全 0x42 payload |
| RewriteRows，保留 index | partial-schema update 显式 Rows 强制走 v2 非索引路线 | 同上 | 同上 |
| drop index 后 RewriteColumns | 非索引 Columns patch | 丢弃返回的 peak，没有上限断言 | 同上 |
| 重建覆盖全部数据的 index 后 Auto | covering-index Take 路径 | 丢弃返回的 peak，没有上限断言 | 同上 |

四阶段入口及断言见[测试流程](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/tests/merge_insert_memory_bound.rs:202)。显式 Rows 让 partial update 绕开 scalar index 的生产条件见[路由](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/src/dataset/write/merge_insert.rs:3049)。

不能据这个测试声称以下事项已证明：

- **所有路径在 48 MiB 内存下完成。** 48 MiB 是配置的 DF pool；前两阶段容许 allocator 计数增长 128 MiB。计数针对经 Rust `GlobalAlloc` 请求的 live heap bytes，排除了执行前已存在的 source/dataset 基线，不是 RSS、cgroup 或所有外部分配的上限；`memory://` 数据本身已驻留。后两阶段没有峰值门禁。[计数器](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/tests/merge_insert_memory_bound.rs:40)
- **实际执行 pool 身份已检查。** 代码断言的是另建 `LanceExecutionOptions` 解析出 48 MiB 且 spilling 开启，没有拿到此次 merge 实际 TaskContext 的 pool 做 identity/reservation 断言。执行成功及 allocator 门禁是另外两项证据，不能替代这个缺口。
- **D 避免了早取大 payload。** source 已包含 1 MiB payload，只有小 Utf8 tag 遗漏。第二阶段注释称“fills payload from target”，与实际输入不符。DP 能触发 late tag，但这不是宽遗漏旧 payload 的容量回归；该证据来自 D/DB/DP 专用 matrix 和 condition 测试。
- **每阶段都验证一次新值落盘。** 第一阶段后四个目标行已经是相同 0x42；后续阶段重复写相同值。stats 仍要求 4 updates，但 readback 不能区分“再次写入成功”与“保留上一阶段结果”。
- **所有行内容及 key 映射均正确。** `check` 不投影 key，也不保存未更新 payload 的原值/hash；只能证明计数、长度和 tag。错改另外四个 key，或破坏未更新 payload 内容但保持长度，不一定失败。[readback oracle](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/tests/merge_insert_memory_bound.rs:135)

这些是结论边界，不是本轮要求改写上游测试的理由。独立运行仍有价值：它把 P 的 indexed 未覆盖 scan、显式 Rows 和两种 Columns/Take 外围带到真实 execute/commit 路径。

## 3. 现有 suite 对外围与 DP 的补充

| 风险 | 已有测试及实际区分力 | 本轮执行归属 |
| --- | --- | --- |
| indexed 候选去重及准确匹配 | `test_indexed_merge_insert_deduplicates_cross_batch_candidates` 给两个 join key 都建 index，跨 source batch 产生重叠候选，验证所有四个 tuple 的值；`test_indexed_merge_insert_composite_key` 的 `index_on_both` case 同样真正走 indexed | DP 完整 Rust merge suite；纯 P 的 integration 不替代这个值级检查 |
| indexed Left 的 source-only 插入 | `test_indexed_merge_insert_composite_key_delete_with_insert` 使用完整 source schema、两个 key 均有 index，验证一个旧 tuple 被删除、新 tuple 插入且值正确；这补充 integration 的 DoNothing/Inner-only 范围 | DP 完整 Rust merge suite |
| index 未覆盖 fragments | `test_indexed_merge_insert_composite_key_unindexed_fragments` 混合已索引与新 fragment，断言两次 update 和行数；值 oracle 较弱，需结合其他 indexed 用例和 integration | DP 完整 Rust merge suite；P/DP integration |
| Columns 条件与遗漏列 | `test_merge_insert_subcols_in_place_update_if_reads_omitted_column` 检查 plan 不扫描 other 且由 condition Take 取得，真实执行断言 update 数；`test_merge_insert_subcols_in_place_update_if` 进一步检查更新前后值及 fragments | DP 完整 Rust merge suite |
| Columns 多文件异构布局 | `test_merge_insert_subcols_in_place_heterogeneous_layouts` 先给一个 fragment 叠加列文件，再追加单文件 fragment，随后跨两者更新并验证 key/tag/other | DP 完整 Rust merge suite |
| Python Columns binding 与文件版本 | `test_merge_insert_subcols_in_place` 显式 rewrite_columns，2 fragments，四组 base/patch storage versions，验证完整表、投影+filter、重复 take、fragment 身份及不允许 insert 的错误 | 已排队的各候选 Python `test_dataset.py -k merge_insert`；不是只检查 plan |
| DP source/target 反向后的 action 映射 | `test_partial_merge_conditions_inserts_deletes_and_duplicates` 在两 fragments 上混合条件更新、重复 source、插入、target-only 删除和 NULL，检查完整结果；Fail/FirstSeen 分开 | DP 完整 Rust merge suite |
| DP stale 地址与 payload | `test_partial_merge_retry_refreshes_payload_and_row_address` 竞争写入移动地址、改变遗漏 payload，旧 job 真实重试，验证第二次匹配及新 payload | DP 完整 Rust merge suite |
| 条件值复用、拒绝行不取 payload、原行映射、NULL、分块与取消 | `condition::tests` 的机制断言；不是只靠最终行值推断少 Take | DP 完整 Rust merge suite；`late-jump.patch` 补突增值序列 |
| 固定 source build 的反例 | `test_unknown_wide_source_exhausts_fixed_source_build_pool` 在 1 MiB pool 中执行 4096×512-byte source、8 行 target，要求资源错误、原版本和值不变 | DP 完整 Rust merge suite；这是直接执行 physical plan 的失败测试，不是成功 commit 或全链路硬内存界 |
| source 尾部错误及跨批重复修改 | 本轮 `test_merge_semantics.py` 用 131073 行首批跨 B row 阈值，验证 tail 错误、默认 Fail、条件拒绝后唯一真正 update 及最新 snapshot | 已排队各候选 Python driver；只有 B/DB 可据实现解释为预读 fallback |

可定位源码：[indexed 去重](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/src/dataset/write/merge_insert.rs:6156)、[indexed delete+insert](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/src/dataset/write/merge_insert.rs:6618)、[Columns 异构布局](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/src/dataset/write/merge_insert.rs:10020)、[Python Columns](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/python/python/tests/test_dataset.py:3004)、[DP 混合 action](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/DP/source/rust/lance/src/dataset/write/merge_insert.rs:17004)、[DP retry](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/DP/source/rust/lance/src/dataset/write/merge_insert.rs:17080)、[DP reverse](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/DP/source/rust/lance/src/dataset/write/merge_insert.rs:11570)。

Python `test_merge_insert_use_index` 的真实 execute 使用 `use_index(False)`；True 分支只验证 explain 不支持。`test_merge_insert_analyze_plan_matches_execute_routing` 只运行两次 analyze 并检查 source shape/Left join 字符串。两者都不能作为 indexed execute 或正常 execute/analyze pool 身份一致的证据。[Python 用例](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/python/python/tests/test_dataset.py:3830)

## 4. 可保留的明确未验范围

1. **真正 indexed 的 composite NULL。** 现有 `test_indexed_merge_insert_composite_key_null_semantics` 只给 a 建 index，join 使用 a,b；当前路由要求所有 join keys 都有 index，因此实际回退非索引。现有两 key 均建 index 的 composite 用例没有 NULL。该名称不能支撑 indexed post-filter NULL 已验证的结论。代码中仍明确设置单 key NullEqualsNull、复合 key NullEqualsNothing；这是实现事实，运行覆盖尚缺。[仅 a index 的用例](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/src/dataset/write/merge_insert.rs:6282)、[全 key index 路由条件](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/ports/P/source/rust/lance/src/dataset/write/merge_insert.rs:3066)
2. **indexed/Columns 的广泛资源和性能收益。** 当前 Rows 非索引 matrix 不测它们。integration 的后两阶段没有峰值 assert，也不检查 Take 请求/page read/scan 并行数量；并发 merge、不同存储延迟、极宽单值、压缩/分布偏斜及真实 cgroup/RSS 都没有由此测试建立上限。
3. **完整 P 与 DP 的逐路径等价。** DP 的 lib suite 可以验证组合后已有语义，不能替代纯 P 的每个独立二进制结果。若纯 P 完整 lib suite 本轮未跑，报告就按“P integration + Python + matrix、DP 完整 lib”列出证据，不合并成“两者全量 Rust 已通过”。
4. **D 不适用路径的收益。** scalar-index、Columns、full source、blob 或不支持的遗漏类型回到原路径。外围回归通过不代表这些路径享有 D 的 late-payload 优化；同样不能将绕开 scalar-index 的显式 Rows 案例描述为 indexed 优化。
5. **预读停止边界所有语义。** 本轮 Python 补充没有 FirstSeen binding，不覆盖 FirstSeen 跨预读边界、100 MiB 字节跨限、慢 producer 或无限空批；已有 Rust FirstSeen/retry 覆盖不同问题。

本轮若只对非索引 Rows 核心机制和实际测得的容量/吞吐作技术结论，上述外围未验范围可明确保留。若要宣称 DP 完整替代 P，或发布覆盖所有 indexed/Columns 的资源承诺，则需要补针对性的运行 oracle 和资源验证；不能靠扩大现有测试名称解释来消除缺口。

## 5. 对 cost-mechanism.md 的措辞修订

本次只收窄报告中的三处描述，未改任何冻结实现：将共同 TaskContext 明确限定为非索引 v2 路径；说明 P 的 Some(1) 在 pool 创建之后才改分区数、indexed 执行仍另取 context；将 D 的 `pool/8/partitions` 明确写成软目标计算而非 pool 划拨，补充 1-byte 下限及无穷/未知 pool 的 16 MiB 目标。固定 source build 的说明也限定到普通非索引 v2 join，避免外推 provider 子计划或全部外围。
