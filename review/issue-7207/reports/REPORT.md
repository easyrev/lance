# #7207 交付报告：回收失败提交留下的索引目录

- 实现分支：`fix/7207-failed-commit-index-cleanup`（commit `ab6f31589`）
- 实现基线：`upstream/main` = `d8293547c`（2026-11-16，"fix(json): parse complete JSONPath numeric literals (#10876)"）
- 计划基线：`31bf831`；开工时 upstream/main 已前进 3 个提交（见 §1）
- 环境：macOS aarch64，Rust 1.98.1（`rust-toolchain.toml` 固定），仓库 cargo 经由 mbx 构建缓存

## 0. 结论

`commit_transaction` 在"本次调用返回 Err，且本次调用发起过的每一次 manifest 写入都被 `verify_commit_outcome` 判定为 `Foreign`/`Absent`"时，删除本事务 mint 出来、且最新 manifest 不再引用的 `_indices/{uuid}` 目录。清理是显式 opt-in，只对 `commit_rewrites`（compaction 的 Rewrite 提交）和 `CreateIndexBuilder::execute` 的单段路径生效；其余调用方（尤其 `CommitBuilder::execute`）保持关闭，以保留"调用方复用同一批段重试"的正确性。

T1–T9 全部有测试且通过；5 项变异检查全部按预期杀死对应测试（T4/T5 需要补强用例，见 §5）。非测试代码净增 239 行（新增 246、删除 7），在 C8 的约 250 行内。

## 1. 基线与计划漂移

计划写于 `31bf831`。开工时最新的 `upstream/main` 是 `d8293547c`，比它多 3 个提交。按计划"行号会漂移，按符号名重新定位"的指示处理，未触发停止条件。实际影响：

1. `commit_compaction` 已被拆成 `commit_compaction` + `commit_rewrites`（repack 系列提交）。opt-in 接在 `commit_rewrites` 末尾、真正提交 `Operation::Rewrite` 的那个 `apply_commit` 上。
2. `commit_transaction` 的非测试调用点不是 2 个而是 3 个：除 `dataset.rs::apply_commit_with_expected_latest_version` 与 `CommitBuilder::execute` 外，还有 `dataset/optimize/commit.rs::reserve_fragment_ids`（`Operation::ReserveFragments`，同一批提交引入）。新调用点传 `ReclaimOnLoss::None`。
3. `commit_transaction` 本身未重构，`CommitOutcome` 仍是 `Ours`/`Foreign`/`Absent`/`Unknown` 四变体，`check_txn` 仍在写 manifest 之前用 `?` 返回冲突。

## 2. 第 4 节第 2 步：三项核对结论

| 核对项 | 结论 |
| --- | --- |
| 索引目录写在 `dataset.indices_dir().join(uuid)` | **成立**。`LanceIndexStoreExt::from_dataset_for_new`（`rust/lance/src/dataset/index.rs:398`）返回以 `indices_dir()/{uuid}` 为根的 store；scalar remap（`index/remap.rs`）和 vector remap（`remap_index_file*`）都经它写文件。`execute_uncommitted_impl` 的 vector/scalar 分支同样用 `dataset.indices_dir().join(index_id.to_string())`（`index/create.rs`）。 |
| rebase 可能换掉 `frag_reuse_index.uuid` | **成立**。`conflict_resolver/finish.rs::finish_rewrite` 在 v0 条目被 trim/restamp 或由 tagged 转 v0 时调用 `build_frag_reuse_index_metadata`，后者 `Uuid::new_v4()`（`index/frag_reuse.rs:966`），详情超过内联上限时还会写 `details.binpb`。tagged 组装路径不产生 uuid 目录。实现因此在每次 `transaction = rebased` 之后重新采集。 |
| `commit_transaction` 的非测试调用点数 | **不成立（计划说 2 个，实际 3 个）**。多的一个是 `reserve_fragment_ids`，见 §1；已传 `None`，不改变行为。 |

## 3. 改动摘要

非测试代码：

- `rust/lance/src/io/commit.rs`
  - `pub(crate) enum ReclaimOnLoss { None, MintedIndexDirs }`（默认 `None`）。
  - `struct MintedIndexDirs { uuids: HashSet<Uuid>, has_unverified_write: bool }`：C1 的布尔状态 + C4 的候选集合。
  - `fn minted_index_uuids(&Operation) -> Vec<Uuid>`：`Rewrite` 取 `new_id != old_id` 的 `new_id` 与 `frag_reuse_index.uuid`；`CreateIndex` 取 `base_id.is_none()` 的 `new_indices[].uuid`；其他变体为空。
  - `commit_transaction` 拆成外层 + `commit_transaction_inner`。外层构造跟踪状态、`Box::pin` 调用内层、仅在 `Err && MintedIndexDirs && !has_unverified_write` 时清理；内层只在 4 处动逻辑：入口采集（外层做）、rebase 后采集、`write_manifest_file` 前置位、两个 `Foreign | Absent` 分支清除。
  - `cleanup_minted_index_dirs`：`resolve_latest_location` + **直接 `read_manifest`** 读最新 manifest 的索引列表（避开 Dataset 缓存），失败则一个都不删；对剩余 uuid 调 `remove_dir_all`，NotFound 忽略，其他失败 `warn!`。读缓存会覆盖同版本 in-memory transaction 的坑见 §5。
- `rust/lance/src/dataset.rs`：新增 `pub(crate) apply_commit_reclaiming_minted_index_dirs`；`apply_commit` / `apply_commit_with_expected_latest_version` 行为不变（`None`）。
- `rust/lance/src/dataset/optimize/commit.rs`：`commit_rewrites` 的 `apply_commit` 换成新方法；`reserve_fragment_ids` 传 `None`；注释说明数据文件仍留给 GC。
- `rust/lance/src/index/create.rs`：单段 `execute` 的 `apply_commit` 换成新方法；多段 FM-Index 等其余调用点不动。
- `rust/lance/src/dataset/write/commit.rs`：`CommitBuilder::execute` 传 `None`。

测试代码：

- `io/commit.rs` 测试模块：T1（采集单测）、T9（最新 manifest 引用保护）、C1 `Foreign` 分支的定向测试。
- `dataset/optimize/tests.rs`：`Race::Delete`、`index_dir_names` 辅助函数。
- `dataset/optimize/tests/commit.rs`：T2、T3–T5（同一 `rstest`，5 个 case）、T6，以及 `LandDropThenFail` 测试 handler。
- `dataset/write/commit.rs` 测试模块：T8。
- `index/create.rs` 测试模块：扩展两个现有 preempted 测试（T7）。

`git diff --stat`（实现 commit）：

```
 rust/lance/src/dataset.rs                       |  41 ++-
 rust/lance/src/dataset/optimize/commit.rs       |  11 +-
 rust/lance/src/dataset/optimize/tests.rs        |  18 ++
 rust/lance/src/dataset/optimize/tests/commit.rs | 351 ++++++++++++++++++++
 rust/lance/src/dataset/write/commit.rs          |  95 +++++-
 rust/lance/src/index/create.rs                  |  39 ++-
 rust/lance/src/io/commit.rs                     | 405 +++++++++++++++++++++++-
 7 files changed, 952 insertions(+), 8 deletions(-)
```

非测试代码净增 **239** 行（新增 246、删除 7；按各文件 `mod tests` 之前的 hunk 统计）。

## 4. C1–C8 对照

| 约束 | 落实 |
| --- | --- |
| C1 删除条件 | 单一布尔 `has_unverified_write`，默认 `false`；写前 `true`；只在两个 `Foreign | Absent` 分支清 `false`；`Ours`/`Unknown`/写后 `ensure_branch_exists`/`record_successful_commit` 都不清。外层只在 `Err` 且为 `false` 时清理。 |
| C2 重试之间不删 | 清理只在外层、内层整体返回后。T6 钉住。 |
| C3 所有权 | 默认 `None`；只 `commit_rewrites` 与单段 `CreateIndexBuilder::execute` 打开；`CommitBuilder::execute` 等保持 `None`。T8 钉住。 |
| C4 只删新 id | `minted_index_uuids` 按 `Operation` 变体计算；`new_id == old_id` 过滤；`CreateIndex` 跳过 `base_id.is_some()`；入口采集 + 每次 rebase 后并集。T1 钉住。 |
| C5 删除前复核最新 manifest | `cleanup_minted_index_dirs` 从存储解析最新 location 并 `read_manifest`，读出的索引 uuid 从候选中剔除；解析/读取失败都不删。T9 钉住。 |
| C6 尽力而为 | 清理错误只 `warn!`；测试断言原始错误类型/文案（`simulated ...`、`CommitStatusUnknown`、`preempted by concurrent transaction Delete`）。 |
| C7 成功路径零改动 | 成功路径不读索引列表、不删除、无新增 IO；只多了一次仅 CPU 的候选集合构造（空集合不分配）。T6 断言成功。 |
| C8 改动面 | 非测试代码只改 `io/commit.rs`、`dataset.rs`、`dataset/write/commit.rs`、`dataset/optimize/commit.rs`、`index/create.rs`；新增类型/方法均 `pub(crate)` 或更窄；净增 239 行。 |

## 5. 测试与变异检查

### 5.1 T1–T9

| 编号 | 测试名 | 约束 | 结果 |
| --- | --- | --- | --- |
| T1 | `io::commit::tests::test_minted_index_uuids_collects_only_new_ids` | C4 | PASS |
| T2 | `dataset::optimize::tests::commit::test_delete_conflict_reclaims_remapped_index_dir` | C1 出口 1 | PASS |
| T3 | `...::test_rewrite_commit_failure_preserves_or_reclaims_index_dirs::case_1_verified_absent` | C1、C6 | PASS |
| T3' | `io::commit::tests::test_foreign_commit_outcome_reclaims_minted_index_dir` | C1 `Foreign` | PASS |
| T4 | `...::case_2_landed_then_propagated_error` | C1（#8118 坏情况） | PASS |
| T5 | `...::case_3_landed_without_verification` | C1 `Unknown` | PASS |
| T4' | `...::case_4_landed_then_index_dropped` | C1（C5 无法兜底的部分） | PASS |
| T5' | `...::case_5_unknown_then_index_dropped` | C1 + `Unknown` | PASS |
| T6 | `...::test_retry_after_concurrent_append_keeps_index_dirs` | C2、C7 | PASS |
| T7 | `index::create::tests::test_create_index_after_concurrent_schema_change`（drop/cast 的 preempted 分支加目录断言） | C1、C3 | PASS |
| T7' | `index::create::tests::test_concurrent_create_index_same_name_returns_retryable_conflict`（加目录断言） | C1、C3 | PASS |
| T8 | `dataset::write::commit::tests::test_failed_commit_keeps_caller_owned_index_segment` | C3 | PASS |
| T9 | `io::commit::tests::test_cleanup_keeps_index_dir_referenced_by_latest_manifest` | C5 | PASS |

补充说明：

- **T3 的 `Foreign` 子场景**放在 `io/commit.rs`，直接调 `commit_transaction`（`CommitConfig { num_retries: 1 }` + 注入 foreign manifest），而不是走 compaction 的 20 次重试耗尽：后者仅 backoff 就会超出 AGENTS.md 的 1 秒预算。覆盖的是同一个 `Foreign | Absent` 清除分支。
- **T4/T5 补强**：按计划做变异"只要 Err 就删"时，原 T4/T5 仍然通过——因为 C5 会在删除前看到"最新 manifest 引用了该 uuid"而跳过（T5 中 `fail_resolve` 也不影响 `resolve_latest_location`）。也就是说原用例钉不住 C1。为此新增 `case_4`/`case_5`：commit 落地后，由测试 handler 在返回错误前再提交一个删除该索引的版本，使最新 manifest **不**引用 minted uuid；此时只有 C1 能保护目录，同时断言 commit 落地的那个历史版本仍可按索引查询。这正是 C5 单独不足的原因（time travel 到旧版本仍会引用）。

### 5.2 变异检查（结果均符合"必须先修测试"的要求）

| # | 变异 | 应失败 | 实际 |
| --- | --- | --- | --- |
| 1 | 去掉外层清理调用 | T2、T3、T7 | T2 FAILED；T3 `case_1_verified_absent` FAILED；T7 两个用例 FAILED |
| 2 | C1 改成"只要 Err 就删"（去掉 `!has_unverified_write`） | T4、T5 | 原 `case_2`/`case_3` 仍 PASS（被 C5 兜住）；补强后 `case_4`、`case_5` FAILED |
| 3 | 把清理挪进 `Foreign | Absent` 分支（重试前就删） | T6 | T6 FAILED |
| 4 | 让 `CommitBuilder::execute` 传 `MintedIndexDirs` | T8 | T8 FAILED |
| 5 | 去掉 `new_id != old_id` 过滤 | T1 | T1 FAILED |

### 5.3 过程中发现并修复的真实回归

cleanup 最初用 `dataset.latest_manifest()`。该路径经 `Dataset::load_manifest`，会把最新 manifest 的内联 transaction 解码并**写入 session 缓存**，覆盖同版本原本的 in-memory transaction。现有测试 `dataset::optimize::tests::frag_reuse::test_index_creation_racing_deferred_compaction_with_stable_row_ids`（Inverted × `index_commits_first=false` × InMemory 两个 case）因此从 PASS 变 FAILED；在未改动的 base 上 16 个 case 全 PASS，确认是本改动引入。改为 `commit_handler.resolve_latest_location` + `read_manifest` 直读后恢复。这也更符合 C5"从存储读"。

## 6. 验证命令与结果

在仓库根目录执行（cargo 经由仓库环境的 mbx；`target` 是 `~/Library/Caches/mbx` 下的托管目录）。

| 命令 | 结果 |
| --- | --- |
| `cargo fmt --all -- --check` | PASS（exit 0） |
| `cargo clippy --all --tests --benches -- -D warnings` | **FAIL，预先存在**：`rust/lance-encoding/src/encodings/physical/byte_stream_split.rs` 的 aarch64 分支 `unreachable expression`（`unreachable-code` 被 `-D warnings` 提升）。该文件未被本改动触碰；在 base 的同等代码上同样触发。 |
| `cargo clippy -p lance --tests --benches -- -D warnings -A unreachable-code` | PASS（7m24s），仅放行上述预先存在 lint |
| `cargo test -p lance --lib io::commit` | 371 passed, 0 failed, 2 ignored |
| `cargo test -p lance --lib dataset::optimize` | 692 passed, 0 failed, 2 ignored |
| `cargo test -p lance --lib index::create` | 93 passed, 0 failed |
| `cargo test -p lance --lib dataset::write::commit` | 19 passed, 0 failed |
| `RUSTDOCFLAGS="-D warnings" cargo doc -p lance --no-deps` | PASS（文档生成成功） |

没有"改动前就失败"的测试需要单列：上述四个套件在实现完成后全绿；唯一一次红是 §5.3 的回归，已修复。

## 7. 泄漏量对比

复现程序在 `review/7207-failed-commit-index-cleanup` 分支（`rust/lance/src/io/commit/repro_7207.rs`，仅该分支，不进实现分支）。数据：200 行 / 20 个 fragment、一个 BTree 索引；重复 20 次"规划并执行 compaction → 提交前注入一个冲突的 Delete → 提交失败"；度量最新 manifest 未引用的 `_indices/{uuid}` 目录数与字节数。

命令：

```bash
cargo test -p lance --lib repro_7207 -- --nocapture
```

| 版本 | 未被最新 manifest 引用的目录数 | 字节数 |
| --- | --- | --- |
| base `d8293547c` + repro | 20 | 72,760 |
| `fix/7207-failed-commit-index-cleanup` + repro | 0 | 0 |

原始输出见 review 分支的 `review/7207-results.md`。

## 8. 已知缺口（确认/可能泄漏但不在本 PR 范围）

1. **调用方自带事务**：`CommitBuilder::execute`、`commit_existing_index_segments`、`execute_uncommitted` 产出的段。调用方可能拿同一批 uuid 重试提交，因此按 C3 不回收；T8 钉住。
2. **成功提交后遗留的 fragment-reuse 目录**：v0 FRI 详情超过内联上限时，每次 rebase 的 `build_frag_reuse_index_metadata` 都会 mint 新 uuid 并写 `details.binpb`。若第一次尝试 `Foreign`、第二次成功，第一次的目录会泄漏。C7 要求成功路径零改动，明确不处理。
3. **多段 FM-Index / `optimize_indices`**：`CreateIndexBuilder` 的其他 `apply_commit` 保持关闭；这些路径在提交前也会写段目录，失败时仍泄漏。
4. **detached 提交 / 新建数据集提交**：不经过本路径的 opt-in。
5. **tagged fragment reuse 组装条目**：不写 uuid 目录，无泄漏。
6. **FTS 半写入目录**（issue 里 rafidowla 报告）：未处理。
7. **提交成功、但 manifest build 在 remap 之后撤下了某个索引**（如覆盖被 invalidated）：当前只在失败路径回收，成功路径可能留下未被引用的 remap 目录；未实测确认，记录为可能缺口。
8. **`base_id.is_some()` 的外部索引**：C4 要求跳过，因此即使 mint 了目录也不回收（实际不会被 mint）。

## 9. 假设与不确定处

- 清理用 `resolve_latest_location` + `read_manifest` 直读存储，而不是 `Dataset::latest_manifest()`；动机见 §5.3。代价是拿不到 `load_manifest` 的 schema/metadata 后处理，但这里只需要 `index_section`。
- `remove_dir_all` 在对象存储上语义因 provider 而异（list+delete）；只在确认失败的路径调用，接受其成本。
- T3 的 `Foreign` 子场景没有走 compaction 的重试耗尽（预算原因），见 §5.1。
- 计划的变异 2 与 C5 存在语义重叠（C5 会兜住已落地但被引用的目录）；用 drop-after-landing 用例补强，见 §5.1/§5.2。
- 未在 S3/GCS 等对象存储上跑测试；本地文件系统与 `memory://` 覆盖。

## 10. PR 描述草稿（英文，未发布）

```markdown
# fix: reclaim index directories of commits verified as not landed

## Problem

Compaction and single-segment index creation write a fresh `_indices/{uuid}`
directory before they commit. When the commit ends up not landing (the
common case being a concurrent DELETE preempting a Rewrite, as in #7207), the
directory is orphaned until `cleanup_old_versions`, which waits seven days.

Deleting on any `Err` is not safe: a commit may have landed while the store
reported a conflict or an I/O error, and a rebase can mint a new fragment-reuse
UUID per attempt.

## When directories are reclaimed

Only when the call returns `Err` **and** every manifest write the call made
has been verified as `Foreign` or `Absent` by `verify_commit_outcome`. A
single flag, set before each manifest write and cleared only in those two
branches, encodes this; `Ours`, `Unknown`, and errors after a successful write
keep it set. Cleanup happens once, after the retry loop, never between
attempts. Before deleting, the latest manifest is re-read directly from storage
(bypassing dataset caches); any UUID it references is kept. Failures only log.

## Why only two call sites opt in

`commit_compaction` (via `commit_rewrites`) and `CreateIndexBuilder::execute`
mint their directories inside the call and rebuild them with new UUIDs on a
retry. `CommitBuilder::execute` and the other `apply_commit` callers may replay
the same transaction (same UUIDs), so reclaiming would leave a successful
retry pointing at a deleted directory. `ReclaimOnLoss` defaults to `None`.

## Tests

T1 collection unit test; T2 delete-preemption; T3 verified-absent and foreign;
T4 landed-but-error with propagation; T5 unknown status; T6 retry after a
concurrent append; T7 preempted CreateIndex (two existing tests extended); T8
caller-owned segment replay; T9 latest-manifest protection.

Mutation checks: removing cleanup fails T2/T3/T7; deleting on any `Err` fails
the landed-then-index-dropped cases (C5 alone cannot protect a non-latest
version); reclaiming between retries fails T6; opting `CommitBuilder` in fails
T8; dropping the `new_id != old_id` filter fails T1.

## Leak measurement

Twenty failed compaction commits on a 200-row, 20-fragment table with one
BTree index: before this change 20 orphaned index directories remained; with
this change 0.

## Out of scope

Caller-owned transactions, detached/new-dataset commits, `optimize_indices`,
multi-segment FM-Index builds, successful-commit leftovers (including
fragment-reuse directories minted by an earlier retried attempt), and the FTS
half-written directories from the issue report.
```
