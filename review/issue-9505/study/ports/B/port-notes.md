# B 移植记录

基线：`0a0d327082988018a25f56147d3b6d02f6c79ecc`。原始 B：`793e4e27119540a17ae37ce78d4f5f4d52060a93`，其父提交为 `dc53d5d174af62c49ddd98d1024a64488c1e4404`。

使用 `git show` 读取原始对象，逐文件三方合并到新基线；三个文件均自动无冲突。未修改原 checkout 或冻结 worktree。source/ 只包含这三个修改文件，implementation.patch 相对于统一基线。

## 保留的机制

- 原始 B 的 100 MiB 及新建 SessionConfig 的 DF 行阈值预读；只有 EOF 才暴露完整 MemTable 统计。完整越界 batch 留在前缀，fallback 以 prefix + 原尾流继续。没有新的 batch/time 限制、pool 派生预算或 disk-prefix 回退。
- 小型 FirstSeen 输入沿原有源顺序去重，再 materialize 取得完整统计；较大输入继续原流式去重。源能重读并不扩大 allow_replay 授权。
- B 原有 planning、execute、analyze 各自取得 bounded context 的行为原样保留，未改成 D 的共享 pool 身份。准备阶段的缓存不向 DF pool 记账。
- Python 仅继承 B 的文档和测试修改；未改变 Python binding。

## 与统一基线的集成

基线在 B 之后新增的无 update 时旧字段填 NULL 及 delete-only 投影行为被完整保留。B 的生产修改未触及这些语义，无需移植专用修补。没有添加 late payload、selector、native scan、格式变更或新阈值。

## 验证状态

仅执行补丁可应用检查及应用后逐字节与 source/ 比较，均通过。未编译、未运行测试、未运行代码 lint；运行验证由主 agent 负责。纯 B 未执行重新格式化，以保持原始实现字节及其移植差异清楚。文件 SHA256 与机制边界见 mechanism.json。

## 机制代价与维护边界

100 MiB 是开始下一次 poll 的停止判断，不是硬驻留上限。整批到达后才能检测越界，越界批仍加入 prefix；一个 batch 可以远大于预算。Arrow get_array_memory_size、底层共享 buffer、Vec 元数据、FirstSeen tracker、HashJoin 状态与 RSS 的口径不同。仅有字节/行数停止条件，没有 batch/time 上限：大量空批次可以持续增长元数据，慢 producer 会直接延长准备屏障。fallback 保存内存前缀，target build 期间仍可能保留它；retry spill 还可能在后台继续读取。

B 对小完整 source 的收益依赖“观察 EOF 后真实统计使 DF 选择更合适的 build”。对大 source，它支付一次预读及 prefix 所有权管理成本，却可能仍得到相同 StreamingTable 计划；宽 source 更容易在首批跨限。source 完整小、target 窄且更小时，Auto 仍可能 build target，预读不会自动变成收益。

维护成本主要在三个入口 execute / execute_uncommitted / analyze 的一致性，FirstSeen 二次 materialize 的顺序及计数，allow_replay 与物理可重读性的分离，以及 source 错误/空 schema/跨限前缀不丢行。与 D 相比，B 不增加 Take/字段拼接/row-address 生命周期，但会改变源开始被消费的时机。

## 解释对照时的限制

B 相比 U 同时改变 source 准备与项目 bounded session factory，不能把全部差异归因于统计。factory 除 pool 外还设置 sort spill reservation=min(pool/3,40MiB)、既有磁盘临时空间限制并注册 Lance functions；没有显式改 target_partitions。spilling 开启时 planning/execution 各有新 pool；设置 LANCE_BYPASS_SPILLING 后可能复用缓存的无界 session。

## 建议的定向 Rust 验证（尚未执行）

每个 filter 运行 `cargo test -p lance --profile release-with-debug --lib <filter>`。下列 filter 不依赖 overlay feature gate：

- `test_first_seen_dedupes_unmatched_source_rows`
- `test_merge_insert_null_single_on_column`
- `test_merge_insert_partial_composite_key_null`
- `test_duplicate_rowid_detection`
- `test_merge_insert_spill_for_retry_false_fails_fast`
- `test_merge_insert_execute_reader_preserves_error_message`
- `test_source_statistics_prefetch_preserves_large_stream`
- `test_small_stream_with_small_join_pool`
- `test_analyze_plan_reports_the_given_source_shape`

源错误的 Rust 测试覆盖第一批直接报错；B 的 Python `test_merge_insert_reader_error_during_prefetch` 覆盖已取一批后的报错。`test_merge_insert_empty_reader_deletes_unmatched` 覆盖空 reader 与零行 batch 的 target-only delete。现有 large-stream Rust 用行阈值触发 fallback，不能冒充字节跨限、fallback 之后尾流报错、FirstSeen 跨准备停止边界或慢源启动延迟的覆盖。后四项目前是待补验证边界，不修改本轮冻结源码。
