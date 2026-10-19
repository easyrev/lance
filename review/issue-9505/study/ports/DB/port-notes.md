# D+B 组合移植记录

统一基线为 `0a0d327082988018a25f56147d3b6d02f6c79ecc`。D 为 `50e216972e1558ce253bece5db462d8241fde96a`；B 为 `793e4e27119540a17ae37ce78d4f5f4d52060a93`，先独立移植到统一基线，再与 D 三方合并。未修改原 checkout 或冻结 worktree。

## 最终生产机制

B 提供完整小 source 的统计；D 在 eligible current-v2 RewriteRows 中延迟读取 source 缺少的旧字段，并复用条件已经读取的字段。DataFusion 继续普通 Auto 选边。没有 selector、StatsGuard、native scan 或新阈值。

B 的 source 准备函数与本轮纯 B source/ 对应函数逐字节相同：100 MiB + 新建 SessionConfig 的默认 DF 行阈值，EOF 后 MemTable，跨限整批留在内存前缀，prefix + tail 回退；没有把预算派生为 pool 比例，没有新增 batch/time 停止条件。原 retry allow_replay 边界保持不变。FirstSeen 的完整小输入仍沿 B 路径先顺序去重、再 materialize。

D 的 condition.rs 与 logical_plan.rs 逐字节继承。两份 Python 文件逐字节继承移植后的 B。merge_insert.rs 同时保留上游的无 update 时填 NULL、B 的准备/FirstSeen 和 D 的 late payload。

## 五处三方合并冲突

1. create_plan_in_session：采用 D 从外部传入的 session，删除 B 在方法内再次创建 session 的代码。
2. execute_uncommitted_v2：采用 D 随计划返回的 TaskContext，删除 B 单独创建执行 pool 的代码。
3. analyze_plan_provider：采用 D 的 analyze_plan_with_context，显式传入同一 TaskContext。
4. join 选边测试注释：采用 D 对窄投影 fixture 的说明，避免继承 B 关于提前读取 other 的过时描述。
5. retry 测试相邻插入冲突：保留 D 的 partial-schema 条件/重复键/真实冲突重试测试，并采用 B 对 buffered source 仍 fail-fast 的注释。

这使得同一次 attempt 的 planning、FirstSeen materialization、execute、analyze 使用同一个 bounded pool。B 的源预读缓存和既有 retry spill 仍不向该 pool 记账，不能据此声称全进程内存受 pool 严格限制。

## 测试源与归档 D 的差异

归档 D 保留 benchmark checkout 的普通常量 assert；其已通过的测试 checkout 使用 const assert。本组合采用后者，仅把测试中的 `assert!(SOURCE_ROWS * VALUE_BYTES > POOL_BYTES)` 改为 `const { assert!(SOURCE_ROWS * VALUE_BYTES > POOL_BYTES) };`。这一修正不改变生产源码，已单独记录于 mechanism.json。

## 验证状态

补丁可应用于统一基线；应用后所有文件逐字节匹配 source/。来源函数/文件的逐字节继承检查通过。合并后的 merge_insert.rs 已 rustfmt。未编译、未运行 Rust/Python 测试或 Clippy。沿用的 D/B 测试不等于新组合已经通过；运行验证由主 agent 完成。

## 机制对照与维护成本

| 比较 | 可归因的新增机制 | 限制 |
| --- | --- | --- |
| DB 对 D | B 的 EOF source 准备和小 FirstSeen materialize | 同样保留 B 的启动屏障、跨限批和内存 prefix 成本 |
| D 对 CTX | eligible omitted payload 的延迟读取、条件值复用及对应分块 | 仍需按实际命中分布比较 Take 与早读 |
| DB 对 B | D late payload + 同一 pool 身份传递 | 不是单独的 late-payload 消融 |
| B 对 U | source 准备 + bounded session factory | 不是单独的统计消融 |
| CTX 对 U | 项目 session factory 和同一 TaskContext | factory 还设置 sort reservation、磁盘限制并注册函数 |

大输入在未到 EOF 时不会获得新统计，DB 仍支付 B 预读成本。尤其大宽 source 可能第一批就跨限：前缀仍占用整批的 backing buffers，而 D 只能省略 target 中 source 没提供的字段；full-schema source 没有这项 late-payload 收益。若 source 完整但接近100 MiB，会先全部 materialize，再进入 join；不能把该内存只计入 HashJoin pool。

组合维护成本是两条生命周期叠加：source 从 reader 到 prefix / MemTable / retry spill；target 从 snapshot 到 match row-address / condition Take / payload Take。共享 context 消除了规划与执行 pool 脱节，但不会给 source cache、FirstSeen tracker 或整个进程自动建立预算。真实冲突重试必须重新扫描 target 并 Take；B 不能让缓存的 source 夹带旧 target 地址。

## 是否加入自适应 late

当前不加新阈值或自动 writer mode。D 的资格条件是格式/类型/写模式正确性门槛，不是根据 workload 预测收益。稀疏实际更新且旧 payload 宽时，窄 match + 小量 Take 有结构性收益；高覆盖率、高 fanout、跨页随机地址或远端请求延迟可能使早读更合适。source 行数小不能证明 target 更新少，fragment touched 也不能独立代表 page 覆盖。需要本轮 dense/fanout/locality 与远端场景结果后，才判断是否需要选择器。

若未来实现自适应，先确定可观测证据与切换边界，不把所有未知 source 强制物化；whole-commit coverage barrier 只适用于已经有界完整的 action/source 集合。当前 patch 只组合已有生产机制，未为可能的未来策略增加接口。

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
- `test_merge_plan_uses_canonical_memory_pool`
- `test_unknown_wide_source_streams_with_bounded_target_build`
- `test_partial_merge_conditions_inserts_deletes_and_duplicates`
- `test_partial_merge_retry_refreshes_payload_and_row_address`
- `payload_reuses_condition_values_and_preserves_row_mapping`
- `payload_chunks_obey_soft_budget_and_release_pending_reads`

源错误的 Rust 测试覆盖第一批直接报错；B 的 Python `test_merge_insert_reader_error_during_prefetch` 覆盖已取一批后的报错。`test_merge_insert_empty_reader_deletes_unmatched` 覆盖空 reader 与零行 batch 的 target-only delete。现有 large-stream Rust 用行阈值触发 fallback，不能冒充字节跨限、fallback 之后尾流报错、FirstSeen 跨准备停止边界或慢源启动延迟的覆盖。后四项目前是待补验证边界，不修改本轮冻结源码。
