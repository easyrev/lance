# 仅 context 修正对照

统一基线：`0a0d327082988018a25f56147d3b6d02f6c79ecc`。从 D `50e216972e1558ce253bece5db462d8241fde96a` 只提取规划/执行/analyze 共用 context 的修改，产物名为 CTX，避免与历史统一候选 C 混淆。

source/ 仅有 rust/lance/src/dataset/write/merge_insert.rs。生产修改是：增加 TaskContext import；create_plan_with_context 创建项目 bounded session；私有 create_plan_in_session 接受指定 session 并返回其 task context；execute_uncommitted_v2 使用返回 context；analyze_plan_provider 使用 analyze_plan_with_context 传入同一 context。create_plan 仅作为现有说明/测试接口包装保留。

没有提取 D 的 payload_columns、MergeConditionExec 改动、partial-schema 窄投影、条件读取复用，也没有 B 的 EOF 预读、FirstSeen materialize、任何 selector/统计保护/native scan/新阈值。target 旧字段保持统一基线的 early fill；legacy 和文件格式不变。项目默认 pool 或 LANCE_MEM_POOL_SIZE 等已有配置决定预算，LANCE_BYPASS_SPILLING 的已有行为保持不变。

## 覆盖与验证边界

仅继承 D 的两个 context 相关测试：test_merge_plan_uses_canonical_memory_pool 和 test_unknown_wide_source_streams_with_bounded_target_build。第二个使用 full-schema source；其 target 窄投影来自基线已有列裁剪，不依赖 D 的 late payload。采用 D 已记录测试 checkout 的 const assert 修正。没有继承延迟 payload 测试。

补丁可应用于统一基线，应用后逐字节匹配 source/，rustfmt 通过。静态核验 production 中没有 payload_columns、MAX_SOURCE_BUFFER_BYTES 或 selector。未编译、未运行测试、未运行 Clippy；这些检查由主 agent 统筹。

## 归因限定

CTX 提取的是 D 使用既有项目 session factory 的修正，并非只替换 memory-pool 实现的单变量实验。factory 还把 sort spill reservation 设为 min(pool/3,40MiB)，配置既有临时磁盘限额，并注册 Lance functions。没有设置 target_partition，因此仍沿用 DataFusion 的 available-parallelism 默认。D 对 CTX 比较更适合分离 late payload 机制。

## 建议的定向 Rust 验证（尚未执行）

每个 filter 运行 `cargo test -p lance --profile release-with-debug --lib <filter>`。下列 filter 不依赖 overlay feature gate：

- `test_first_seen_dedupes_unmatched_source_rows`
- `test_merge_insert_null_single_on_column`
- `test_merge_insert_partial_composite_key_null`
- `test_duplicate_rowid_detection`
- `test_merge_insert_spill_for_retry_false_fails_fast`
- `test_merge_insert_execute_reader_preserves_error_message`
- `test_merge_plan_uses_canonical_memory_pool`
- `test_unknown_wide_source_streams_with_bounded_target_build`
