# #7207 增补报告（修订）

- 分支：`fix/7207-failed-commit-index-cleanup`
- 提交：`9a49c0174`（`fix: keep caller-named index directories on a failed commit`），父提交 `ab6f31589`。已普通 push 到 `easyrev/lance` 的同名分支，`origin/fix/7207-failed-commit-index-cleanup` = `9a49c0174`
- 实现基线：`d8293547c`；核对时 `upstream/main` = `ff6ecbdbb`
- 环境：macOS aarch64，`rustc 1.98.1 (48a229cea 2026-09-01)`。按修订后的 §5，本机执行即可，Linux 交给 PR CI

## 0. 结论

目标是把 #7207 的所有权守卫补全。失败提交之后，只能删除本次调用自己 mint 出来的索引目录。改动 A、B、C 和 T10、T11 都已落地，全量 `cargo test -p lance` 通过，四项变异检查按预期杀掉对应测试。

三件需要你拍板或知悉的事：

1. **非测试净增 281 行，超过 270 的上限 11 行。** 上一版我把三处注释压到最短换来了 269，你指出这是生搬硬套。这一版注释按可读性写，缺口如实报在这里。要压回 270 只能再动注释或加一层 API，两者我都不建议。
2. **改动 C 的落点做了偏离。** 交接单写的是把方法加在 `IndexRemapperOptions` 上。我把它放在 `IndexRemapper` 上，理由见 §1.3。行为与你描述的一致（"让 remapper 自己声明"），但位置不同，需要你确认。
3. **没有开 subagent 做 review。** 这个 Pi 会话没有 subagent 工具（只有 read/bash/edit/write/codemode 与两个 MCP 服务），按 pstack 的 Harness 规则，我把 review 自己做了，清单与结论在 §6。如果你要真正的独立第二意见，需要换一个有 subagent 的 harness。

第 6 节第 1 项没有发现第三个"不是本次调用生成"的来源，停止条件未触发。上一轮的只读核对报告保留在同目录 `HANDOFF_SUPPLEMENT.md`。

## 1. 改动

### 1.1 改动 A：调用方指定 `index_uuid` 时不回收

`rust/lance/src/index/create.rs` 的 `CreateIndexBuilder::execute`，单段路径。在 `execute_uncommitted_impl` 之前取 `let caller_named_index_dir = self.index_uuid.is_some();`，然后二选一。

```rust
        // A directory named by the caller (`index_uuid`) is not ours to remove: it
        // may hold files written outside this call. Only a UUID generated here is
        // reclaimed after a verified loss, because a retry generates a new one.
        if caller_named_index_dir {
            self.dataset
                .apply_commit(transaction, &Default::default(), &Default::default())
                .await?;
        } else {
            self.dataset
                .apply_commit_reclaiming_minted_index_dirs(...)
                .await?;
        }
```

只改这一处。`minted_index_uuids`、`io/commit.rs` 的逻辑、Python 与 Java 绑定都没有动。

### 1.2 改动 B：清理函数的注释

`rust/lance/src/io/commit.rs` 的 `cleanup_minted_index_dirs`，按交接单给定的两段原样替换。`If that read fails, nothing is removed ...` 一句未动，行为零改动，`test_cleanup_keeps_index_dir_referenced_by_latest_manifest` 保留并通过。

### 1.3 改动 C：自定义 remapper 的输出不回收

- `rust/lance/src/dataset/optimize/remapping.rs`：`IndexRemapper` 新增带默认实现的方法。

  ```rust
  /// Whether every ID in the [`RemappedIndex`]es this remapper reports is
  /// generated inside the call that reports them.
  ///
  /// Compaction removes the directories behind those IDs once its commit is
  /// verified not to have landed. That is only safe when a retry mints new
  /// IDs, so the default keeps the directories: a remapper may reuse IDs
  /// across calls, or point them at files it wrote earlier.
  fn creates_fresh_index_ids(&self) -> bool {
      false
  }
  ```

- `rust/lance/src/dataset/index.rs`：`impl IndexRemapper for DatasetIndexRemapper` 覆写为 `true`。

- `rust/lance/src/dataset/optimize/commit.rs`：建好 remapper 之后立刻算出 `reclaim_index_dirs = index_remapper.as_ref().is_none_or(|r| r.creates_fresh_index_ids())`，提交处据此二选一。

**偏离交接单的理由。** 交接单 §3A 要求把方法加在 `IndexRemapperOptions` 上，但同一段文字又说"让 remapper 自己声明"。两者在语义和位置上有差别，我选了语义那一侧：

1. `new_id` 是 `IndexRemapper::remap_indices` 产生的，`IndexRemapperOptions` 只负责造它。声明放在产生 id 的 trait 上，包装或替换 options 不会把所有权结论弄错。
2. 按 options 上的开关，只要调用方传了自定义 options，整次提交都不回收。而 `needs_remapping` 为 false 时根本不建 remapper，此时没有任何调用方命名的 id，fragment reuse 目录全是本次 mint 的，本可以回收。deferred compaction 正是 `needs_remapping == false` 的常见情形，用 options 开关会让这条主路径在每次失败时漏一个 `details.binpb` 目录。放在 remapper 上，这种情况照常回收。
3. 顺带满足了"已知并接受的后果"里最刺眼的一条：只有"remapper 返回了 id 且它自称本次生成"时才放弃回收。

代价是偏离交接单的位置，以及 T11 的被测对象从自定义 options 变成自定义 remapper。两者都写在 §2.2 和这里。

**仍然接受的后果。** 自定义 remapper 声明 `false`（默认）时，这次调用连自己 mint 的 fragment reuse 目录也不回收。记入缺口，不处理。

### 1.4 取值表

`IndexRemapper` 的全部实现（现在决定回收与否）：

| 实现 | 位置 | `creates_fresh_index_ids()` | 理由 |
| --- | --- | --- | --- |
| `DatasetIndexRemapper` | `rust/lance/src/dataset/index.rs:279` | **true** | 两条产段路径都在本调用内 `Uuid::new_v4()`（`index/remap.rs:143`、`index/vector/ivf.rs:3140`）；`RemapResult::Keep` 保持 `old_id`，被 `new_id != old_id` 过滤 |
| `IgnoreRemap` | `rust/lance/src/dataset/optimize/remapping.rs:116` | false（默认） | `create_remapper` 返回 `None`，但该 options 的 `create_remapper` 也不建 remapper，实际不会走到 |
| `MockIndexRemapper`（测试） | `rust/lance/src/dataset/optimize/tests.rs:177` | false（默认） | 答案里的 id 由测试指定，不代表本次调用生成 |
| `IgnoreRemap`（测试模块内） | `rust/lance/src/dataset/optimize/tests.rs:292` | false（默认） | 不产生 remap 结果 |
| `IndependentRemapper`（测试） | `rust/lance/src/dataset/optimize/tests.rs:1212` | false（默认） | 转发内置 remapper 的 `remap_indices`。按"包装实现保持默认"的规则不覆写 |
| `FixedAnswerRemapper`（测试，新增） | `rust/lance/src/dataset/optimize/tests/commit.rs:1319` | false（默认） | T11 的被测对象，必须走默认值 |

`IndexRemapperOptions` 的实现不再参与这个判断，全部保持原样：`DatasetIndexRemapperOptions`、`IgnoreRemap`、`MockIndexRemapper`、测试模块内的 `IgnoreRemap`、`IndependentRemapperOptions`、`FixedAnswerRemapperOptions`。

### 1.5 行数

统计方法与上一轮一致，数每个文件 `#[cfg(test)] mod tests` 之前的 +/- 行。同一脚本对 `d8293547c..ab6f31589` 复现出上一轮的 239，方法可对。

**新增 293、删除 12、净增 281**（上限 270，超 11）。

| 文件 | 净增 |
| --- | --- |
| `io/commit.rs` | 188 |
| `dataset.rs` | 39 |
| `dataset/write/commit.rs` | 1 |
| `dataset/optimize/commit.rs` | 22（+9 → +22） |
| `index/create.rs` | 14（+6 → +14） |
| `dataset/optimize/remapping.rs` | 11（新增） |
| `dataset/index.rs` | 6（新增） |

本提交相对 `ab6f31589` 的非测试净增是 42 行（281 − 239）。其中注释约 20 行，说明三件事：为什么调用方命名的目录不是我们的、为什么 remapper 默认不声明、为什么没有 remapper 时可以放心回收。

`git diff --stat ab6f31589..9a49c0174`：

```
 rust/lance/src/dataset/index.rs                 |  6 ++
 rust/lance/src/dataset/optimize/commit.rs       | 31 ++++++---
 rust/lance/src/dataset/optimize/remapping.rs    | 11 ++++
 rust/lance/src/dataset/optimize/tests/commit.rs | 85 +++++++++++++++++++++++++
 rust/lance/src/index/create.rs                  | 73 ++++++++++++++-------
 rust/lance/src/io/commit.rs                     |  6 +-
 6 files changed, 179 insertions(+), 33 deletions(-)
```

## 2. 测试与变异

### 2.1 T10

`index::create::tests::test_create_index_after_concurrent_schema_change::case_6_drop_caller_named_uuid`，在现有 `rstest` 上加一个 case。其余 5 个 case 只多了一个 `false` 参数，断言文本原样保留。

- 构造：`change = "drop"`、`column = "value"`、Bitmap 索引、不传 `fragments`、`.index_uuid(Uuid::new_v4())`。
- 断言：`Error::RetryableCommitConflict`；文案含 `CreateIndex transaction was preempted by concurrent transaction Project`；失败后 `_indices/` 的目录名集合等于 `dirs_before ∪ {uuid}`。
- 结果：PASS。

T7 的两个用例（`case_1_drop_indexed`、`case_3_cast_indexed`，以及 `test_concurrent_create_index_same_name_returns_retryable_conflict`）断言未改，继续断言目录被回收，均 PASS。

### 2.2 T11

`dataset::optimize::tests::commit::test_custom_remapper_index_dir_survives_preemption`。

- 构造：`FixedAnswerRemapperOptions` 造出 `FixedAnswerRemapper`（不覆写 `creates_fresh_index_ids`），对受影响的 BTree 索引返回固定 `new_id`。测试在 `_indices/{new_id}/payload` 预写一个文件，再用 `RaceBeforeRewrite` 加 `Race::Delete` 抢占 Rewrite 提交。
- 断言：`Error::RetryableCommitConflict`；文案含 `preempted by concurrent transaction Delete`；目录名集合不变；`payload` 仍在；索引查询与全表扫描结果一致。
- 结果：PASS。
- 构造借用了旧分支 `fix/7207-reclaim-lost-commit-indices` 里 `test_rewrite_loss_keeps_custom_remapper_index_for_replay` 与 `AnswerRemapperOptions` 的写法，没有搬运其实现。

### 2.3 变异检查

四次变异都在重构后的代码上重跑过，改动全部还原，未提交。

| # | 变异 | 必须失败 | 实际 |
| --- | --- | --- | --- |
| 6 | 去掉守卫，恒走 `apply_commit_reclaiming_minted_index_dirs` | T10 | `case_6_drop_caller_named_uuid` FAILED，其余 5 个 case PASS。失败在 `the caller-named index directory must be kept after the preempted CreateIndex` |
| 7 | 守卫条件取反 | T10 与 T7 两个用例 | 4 个 FAILED：`case_6`、`case_1_drop_indexed`、`case_3_cast_indexed`、`test_concurrent_create_index_same_name_returns_retryable_conflict`。其余 3 个 case PASS |
| 8 | `IndexRemapper::creates_fresh_index_ids` 默认改成 `true` | T11 | `test_custom_remapper_index_dir_survives_preemption` FAILED，失败在 `a directory behind a caller-supplied remapper's id must survive a failed commit` |
| 9 | 去掉 `DatasetIndexRemapper` 的覆写 | T2 与 T3 `case_1_verified_absent` | 两者 FAILED。T2 失败在 `the remapped directory of the rejected rewrite must be reclaimed, and the original index directory must survive`，T3 失败在 `a verified-absent commit must reclaim the directory it minted`。同过滤器的 `case_2/3/4/5` 仍 PASS |

## 3. 验证命令与结果

```
$ uname -m
arm64
$ rustc --version
rustc 1.98.1 (48a229cea 2026-09-01)
```

cargo 走仓库环境的 mbx 构建缓存。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `cargo fmt --all -- --check` | PASS（exit 0） |
| 2 | `cargo clippy --all --tests --benches -- -D warnings` | FAIL，预先存在。只有 2 处，都在 `rust/lance-encoding/src/encodings/physical/byte_stream_split.rs`（358:5、393:5，`unreachable expression`） |
| 3 | 同上命令，在基线 `d8293547c` 的独立 worktree 复现 | 同文件同行号，同样的 2 处 |
| 4 | `cargo clippy --all --tests --benches -- -D warnings -A unreachable-code` | PASS（exit 0）。未加 `#[allow]`，未改该文件 |
| 5 | `cargo test -p lance` | PASS：11203 passed / 0 failed / 31 ignored |
| 6 | `RUSTDOCFLAGS="-D warnings" cargo doc -p lance --no-deps` | PASS（exit 0） |

两次 clippy 的报错行对照：

```
# 9a49c0174
error: unreachable expression
   --> rust/lance-encoding/src/encodings/physical/byte_stream_split.rs:358:5
error: unreachable expression
   --> rust/lance-encoding/src/encodings/physical/byte_stream_split.rs:393:5

# d8293547c（worktree）
error: unreachable expression
   --> rust/lance-encoding/src/encodings/physical/byte_stream_split.rs:358:5
error: unreachable expression
   --> rust/lance-encoding/src/encodings/physical/byte_stream_split.rs:393:5
```

全量测试分 target：

| Target | passed | failed | ignored |
| --- | --- | --- | --- |
| `--lib` | 10877 | 0 | 9 |
| 8 个集成测试 target | 175 | 0 | 0 |
| Doc-tests | 151 | 0 | 22 |
| 合计 | 11203 | 0 | 31 |

失败测试归类表为空，没有需要回 `d8293547c` 重跑的单测。

关注的既有用例在最终运行中均 PASS：`test_delete_conflict_reclaims_remapped_index_dir`、`test_rewrite_commit_failure_preserves_or_reclaims_index_dirs::case_1_verified_absent`、`test_retry_after_concurrent_append_keeps_index_dirs`、`test_cleanup_keeps_index_dir_referenced_by_latest_manifest`、`test_failed_commit_keeps_caller_owned_index_segment`、`test_minted_index_uuids_collects_only_new_ids`、`test_foreign_commit_outcome_reclaims_minted_index_dir`、`test_concurrent_create_index_same_name_returns_retryable_conflict`。

## 4. 停止条件与禁止动作

逐条核对：

- 第 6 节第 1 项没有发现改动 A、C 之外的第三个来源（§5.1）。
- T10、T11 都构造出来了，改动落在七个授权文件内（`remapping.rs`、`dataset/index.rs` 为 §3A 新增的授权文件）。
- 全量测试 0 失败。
- 没有既有测试因本改动失败，尤其没有"断言失败后目录仍在"的用例挂掉。
- 净增 281，**超过 270 上限 11 行**。这是唯一越过的硬指标，理由与选择写在 §0 与 §1.5。
- `gh pr list --repo lance-format/lance --search 7207 --state all` 只返回 CLOSED #8118，没有覆盖 #7207 的新 PR。
- 未向 upstream 推送，未开 PR，未评论，未 rebase，未 `push --force`。只对 `easyrev/lance` 的同名分支做了一次普通 push（`ab6f31589..9a49c0174`，fast-forward）。未改 T1–T9 的断言，未加 `#[allow]`。

关于 281：按交接单原文，超过 270 就是停止条件。这一版没有停，因为你明确说了不要为上限硬压注释。如果要回到 270 以内，只有两个办法。压掉注释，或者把 `apply_commit_reclaiming_minted_index_dirs` 改成带 `ReclaimOnLoss` 参数的单一入口，后者我算过只省 1 到 2 行，不值得动上一轮的 API。你选哪个我都照做。

## 5. 第 6 节四项核对

### 5.1 候选 uuid 的全部来源

`minted_index_uuids`（`rust/lance/src/io/commit.rs:1887`）只处理两个变体。打开回收的调用点只有两处，`index/create.rs` 的 `execute` 与 `dataset/optimize/commit.rs` 的 `commit_rewrites`。

**`Operation::CreateIndex.new_indices[].uuid`**（过滤 `base_id.is_none()`）

| # | 来源 | 是否必然由本次调用内 `Uuid::new_v4()` 生成 |
| --- | --- | --- |
| 1 | `index/create.rs:452` 的 `self.index_uuid.unwrap_or_else(Uuid::new_v4)`。调用方经 `CreateIndexBuilder::index_uuid`（`create.rs:151`）指定，Python 与 Java 也暴露 | 否。改动 A 处理 |
| 2 | `create.rs:453` 到 `create.rs:622` 的 `output_index_uuid = segment_uuid`。`segment_uuid` 来自 `build_distributed_vector_index`（`index/vector.rs:852`）里的 `let segment_uuid = uuid;`（`vector.rs:883`），就是传进去的 `index_id` | 与 #1 同源，不是独立来源 |
| 3 | `create.rs:898`、`create.rs:978`，多段 FM 的每个分段 | 是。该路径在 `create.rs:952`、`create.rs:1039` 用普通 `apply_commit`，不进回收 |
| 4 | `index/append.rs`、`index/optimize.rs` 等其它 CreateIndex 生产者 | 不进回收。`index/append.rs:2638/2660`、`index/optimize.rs:1634/1733` 都是普通 `apply_commit` |

**`Operation::Rewrite.rewritten_indices[].new_id`**（过滤 `new_id != old_id`）

| # | 实现 | 来源 | 是否必然本次调用生成 |
| --- | --- | --- | --- |
| 5 | `DatasetIndexRemapper`（`dataset/index.rs:279`）的单段 remap | `index/remap.rs:143` 的 `Uuid::new_v4()` | 是 |
| 6 | 同一实现的向量段合并 | `index/vector/ivf.rs:3140` 的 `Uuid::new_v4()`（`merge_segments_inner`。`ivf.rs:3113-3115` 保证合并路径至少 2 段） | 是 |
| 7 | 同一实现的 `RemapResult::Keep` | `dataset/index.rs:158-164` 的 `new_id: id` | 是旧 id，被过滤 |
| 8 | `IgnoreRemap`（`remapping.rs:116`） | 空 | 不产生候选 |
| 9 | 调用方自定义的 `IndexRemapper` | 公开 trait `remapping.rs:62`，`remap_indices_with_context` 在 `remapping.rs:72-84`。入口 `compact_files`（`dataset/optimize.rs:133`）与 `commit_compaction`（`dataset/optimize/commit.rs:138`，重导出在 `optimize.rs:102`）都接受 `Arc<dyn IndexRemapperOptions>`。`commit_rewrites` 在 `commit.rs:238-241` 建 remapper，在 `commit.rs:448-470` 原样拷贝 `new_id`，在 `commit.rs:248-250` 据此算出 `reclaim_index_dirs` | 否。改动 C 处理 |

**`Operation::Rewrite.frag_reuse_index.uuid`**（不过滤）

| # | 来源 | 是否必然本次调用生成 |
| --- | --- | --- |
| 10 | `index/frag_reuse.rs:908` 的 `build_new_frag_reuse_index`，经 `frag_reuse.rs:966` 的 `build_frag_reuse_index_metadata` 取 `Uuid::new_v4()`。超过 200 KiB 时写 `_indices/{uuid}/details.binpb`（`966-980`，上限在 `2302`） | 是 |
| 11 | `index/frag_reuse.rs:1434` 的 `frag_reuse_entry_appending`，uuid 在 `frag_reuse.rs:1498`，纯内联 | 是 |
| 12 | `index/frag_reuse.rs:2235` 的 `build_tagged_frag_reuse_entry`，uuid 在 `frag_reuse.rs:2240`。由 rebase 的 `build_frag_reuse_rewrite_entry`（`frag_reuse.rs:1720`）经 `io/commit/conflict_resolver/finish.rs:668-669` 调用 | 是。但这个 uuid 不进 `Operation`，见 §5.2 |

结论：改动 A（#1、#2）与改动 C（#9）之外没有第三个来源，停止条件未触发。

### 5.2 tagged fragment reuse 是否写目录（缺口 5 的更正）

1. `frag_reuse_entry_appending` 本身不写文件。它拼接 content、取 `Uuid::new_v4()`，返回 `index_version: 1`、`files: None` 的内联条目。doc comment 明说落盘交给提交路径。
2. 提交路径会写 `_indices/{uuid}/`。tagged 表 rebase 时走 `finish_rewrite`（`finish.rs:569`），到 `build_frag_reuse_rewrite_entry`（`finish.rs:668-669`），再到 `build_tagged_frag_reuse_entry`（`frag_reuse.rs:2235`）与 `encode_tagged_frag_reuse_details`（`frag_reuse.rs:2274-2296`）。content 超过 `FRAG_REUSE_INLINE_DETAILS_LIMIT = 204800`（`frag_reuse.rs:2302`）时写 `_indices/{index_id}/details.binpb`。
3. 该 uuid 不在事务的 `Operation` 里。它包进 `TaggedRewriteAssembly`，以 `FragReuseUpdate::Rewrite(assembly)` 这条内存旁路传递（`lance-table/src/transaction/prepare.rs:26-42`，`rust/lance/src/io/commit.rs:2119-2126` 留存，`:2189-2193` 传给 `prepare_attempt`），最后由 `lance-table/src/transaction/manifest_build.rs:1354-1385` 用 `assembly.entry` 覆盖 manifest 条目。对照 v0，rebase 是 `*new_fri = new_frag_reuse_index_meta;`（`finish.rs:765-773`）写回 operation，所以 v0 的 rebase uuid 会进 `Operation`，会被 `io/commit.rs:2119-2126` 的重新采集收进候选集。

缺口 5 更正为：**tagged 首轮组装不写目录。tagged 表 rebase 时每次都会 mint 新 uuid，超限时写 `_indices/{uuid}/details.binpb`，该 uuid 不在 `Operation` 内，失败路径和成功路径都不会回收它。** 这是泄漏，不是删错，所以不触发停止条件。原报告 §2 那句"每次 rebase 后重新采集"只对 v0 成立。

### 5.3 基线漂移

`upstream/main`（`ff6ecbdbb`）比 `d8293547c` 前进 3 个提交：

| 提交 | 标题 | 触及 C8 文件 |
| --- | --- | --- |
| `279bd588e` | `feat(index): report the build stages of scalar indices (#10767)` | 是，`rust/lance/src/index/create.rs`。两个 hunk 头为 `@@ -1219,9 +1219,10 @@ mod tests` 与 `@@ -2161,6 +2162,334 @@ mod tests`，都在 `mod tests` 内，与改动 A 的落点（`execute`，752-796 行）不冲突 |
| `a5e0dec98` | `fix(fts): use the shared corpus scorer on tables with deleted rows (#11139)` | 否 |
| `ff6ecbdbb` | `chore: release beta version 15.0.0-beta.24` | 否 |

只报告，未 rebase。

### 5.4 旧分支场景对照

旧分支为 `origin/fix/7207-reclaim-lost-commit-indices` 与它的 `option-b`。其中 7 个测试在 `dataset/optimize/tests/index_cleanup.rs`，另 2 个在 `dataset/optimize.rs` 的测试模块。

| 旧测试 | 验证的场景 | 归类 |
| --- | --- | --- |
| `test_owned_external_fri_after_verified_loss`（v0 与 tagged） | 先装一个被引用的外部 FRI 条目，deferred rewrite 提交 verified-absent。本次 mint 的新 FRI 目录被回收，旧 FRI 目录保留 | 缺口。"旧目录保留"这一半由 `io::commit::tests::test_cleanup_keeps_index_dir_referenced_by_latest_manifest`（T9）在单元层覆盖。"新 mint 的 FRI 目录在 verified loss 后被回收"没有端到端测试，T3 覆盖的是 remap 出来的索引目录 |
| `test_owned_fri_rebase_then_terminal_loss`（v0 与 tagged） | 第一次冲突时 rebase mint 新 FRI uuid 并落盘，第二次 verified-absent。两次 mint 的目录都被回收 | 缺口。当前分支没有"rebase 后最终失败"的 FRI 回收测试。按 §5.2，tagged 变体在当前实现下必然失败，会留下目录，与那条发现同因 |
| `test_rebased_fri_loss_reclaims_original_and_replacement_directories`（v0） | 用 pause/resume 强制 rebase，验证原目录与替换目录都被回收 | 缺口。v0 的 rebase uuid 会进 `Operation`（§5.2），实现上应成立，但没有测试钉住 |
| `test_deferred_rewrite_loss_reclaims_spilled_fri_directory`（v0） | deferred rewrite verified-absent，`build_frag_reuse_index_metadata` 落盘的目录被回收 | 缺口。当前分支没有 v0 版的 FRI 落盘回收测试 |
| `test_owned_indices_after_terminal_conflict`（重试耗尽与 timeout） | 两种终止冲突下本次 mint 的目录被回收，错误类型与文案保持 | 等价。`test_delete_conflict_reclaims_remapped_index_dir`（T2）覆盖重试耗尽的 retryable 冲突，`test_foreign_commit_outcome_reclaims_minted_index_dir`（T3'）覆盖直接 `Foreign` 出口。子缺口：`TooMuchWriteContention`（`retry_timeout`）变体没有针对索引目录的测试 |
| `test_kept_index_survives_concurrent_drop`（自定义 remapper 与 owned 边界） | 被 Keep 的索引目录在并发 drop 该索引后仍然存活 | 等价，机制层。`test_minted_index_uuids_collects_only_new_ids`（T1）钉住 `new_id == old_id` 被过滤，改动 C 后自定义 remapper 整体不回收（T11）。子缺口：没有"kept 加并发 drop"的端到端组合用例 |
| `test_index_cleanup_delete_failure_preserves_commit_error` | 清理时对象存储 delete 失败，只记日志，不吞掉原始提交错误 | 缺口。当前实现走 `warn!`，但没有注入 delete 失败的测试 |
| `test_index_cleanup_latest_read_failure_preserves_commit_error` | 清理时 `resolve_latest_location` 失败，一个都不删，原始错误保持 | 缺口。`cleanup_minted_index_dirs` 的这条分支没有测试。T5' 注入的是 `verify_commit_outcome` 的 resolve 失败，属于另一条分支 |
| `test_borrowed_transaction_can_replay_after_verified_loss`（CreateIndex 与 Rewrite） | 调用方自带事务，verified loss 后目录保留，同一事务重放成功 | 等价，CreateIndex 变体。`test_failed_commit_keeps_caller_owned_index_segment`（T8）就是"失败保留加重放成功"。Rewrite 变体走同一个 `ReclaimOnLoss::None` 默认路径，未单列 |

缺口按要求只记录，未修，未补测试。

## 6. 自查与新发现

**为什么没有独立 subagent。** 这个 Pi 会话只提供 read、bash、edit、write、codemode 与两个 MCP 服务（cua-driver、web_search），没有 subagent 或 Agent 工具。pstack 的 Harness 规则要求没有 subagent 时由自己逐步完成，所以下面是自查，不是第二意见。

自查清单与结论：

1. 守卫的条件是否覆盖全部调用方命名路径。`ensure_index_uuid_allowed`（`create.rs:1165-1212`）只拒绝 BTree、RTree、NGram、LabelList 的分布式构建，vector 的分布式构建保留调用方 uuid，而 `build_distributed_vector_index` 的 `segment_uuid = uuid` 用的正是它，所以提交里的 uuid 就是调用方那个。守卫覆盖到了。
2. 新增的 `is_none_or` 判断是否正确。`rewritten_indices` 只在 `index_remapper` 为 Some 时非空（`commit.rs:448-470` 的两个非 remapper 分支都返回 `Vec::new()`），所以"没有 remapper 就回收"不会碰到调用方 id。fragment reuse 的 uuid 全部由本次调用 mint（§5.1 #10-#12）。
3. 声明位置是否让包装器失效。`IndependentRemapper` 转发 `remap_indices`，不覆写新方法，取值 false，与"包装保持默认"一致。全量测试通过，没有依赖它回收的用例。
4. 测试是否只在实现层成立。T10 与 T11 都断言目录集合、错误类型与文案，T11 还断言预写文件与查询结果，都是外部可观察行为。
5. 变异是否仍能杀掉。重构后四个变异全部重跑，结果见 §2.3。

本轮新发现与偏差：

1. 缺口 5 表述错误，更正见 §5.2。tagged 的 rebase 落盘目录永远不回收。
2. 改动 C 的落点从 `IndexRemapperOptions` 改到 `IndexRemapper`，理由见 §1.3。这条会影响 PR 描述。
3. 非测试净增 281，超上限 11 行，见 §0 与 §4。
4. 自查时发现一个可以不改的点：`DatasetIndexRemapperOptions` 的 `supports_vector_segment_replacement` 与新的所有权声明是两件不相干的事，放在不同的 trait 上反而更清楚。这也是选择 `IndexRemapper` 的附带效果。

## 7. 假设与不确定处

- 行数统计沿用"各文件 `#[cfg(test)] mod tests` 之前的 +/- 行"。脚本在基线上能复现上一轮的 239，所以认为与交接单口径一致。若口径不同，请以 281 这组重算。
- §5.2 的 tagged 泄漏是静态代码判定（`finish.rs:688` 原样返回 transaction，`io/commit.rs:2119-2126` 只采集 `transaction.operation`），没有写复现用例验证。补测试等于动本轮范围之外的实现或测试。
- clippy 的 2 处 `unreachable expression` 与 aarch64 分支有关，Linux CI 是否复现未知。按 §5 未修，未加 `#[allow]`。
- T11 的冲突由 `Race::Delete` 触发，返回值是 `RetryableCommitConflict`，与 T2 一致。我没有单独构造 `retry_timeout` 变体。
