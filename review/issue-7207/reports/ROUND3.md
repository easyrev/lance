# #7207 第三轮报告：合并 upstream、补 tagged FRI 与多段 FM-Index

按第三轮交接单执行。fix 分支 `fix/7207-failed-commit-index-cleanup` 新增三个提交，review
分支合并新的 fix 分支并更新 `review/issue-7207/`。

- fix tip：`98f701cc4`
- 合并所用的 `upstream/main`：`134c2bf95`（`build(python): make numpy an optional dependency (#11084)`）
- 合并提交：`d4ee1c879`
- 环境：macOS aarch64（10 核），`rustc 1.98.1`（`rust-toolchain.toml` 固定），本地文件系统存储

## 0. 结论

三件事全部完成，未触发任何停止条件。

- 合并 `upstream/main` 无冲突；合并后 `cargo check -p lance --tests` 通过。
- 两项复核都没有发现“不是本次调用生成、却会进入候选集”的 uuid。
- 改动 1：rebase 组装出的 tagged FRI 条目 uuid 进入候选集，其溢出目录在核实未落地后被回收。
- 改动 2：多段 FM-Index 的两条提交路径都打开回收。
- 两个新测试都构造成功，没有用交接单里的退路；每个用例耗时远低于 1 秒。
- 11 项变异检查（旧 9 项复跑 + 新 2 项）全部按预期失败。
- `cargo test -p lance` 通过：11,380 通过、0 失败、31 忽略。
- 复现程序在 `98f701cc4` 上报告 0 个孤儿目录 / 0 字节。
- `fmt`、`clippy`（`-A unreachable-code`；不带它时只有 `byte_stream_split.rs` 的两处既有报错）、
  `doc`、计划编号检查全部通过。

## 1. 合并与两项复核

```text
$ git fetch upstream && git switch fix/7207-failed-commit-index-cleanup
$ git merge --no-edit upstream/main
$ cargo check -p lance --tests
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 7m 52s
```

合并无冲突。合并进来的 Transaction V2 系列是 #8644、#8645、#8646，另有 #11084 等。
本轮合并时 `upstream/main` 比基线 `d8293547c` 多 15 个提交。

### 1.1 两个打开回收的调用点仍然构造旧式操作

- `commit_rewrites` 构造并提交 `Operation::Rewrite`（`rust/lance/src/dataset/optimize/commit.rs:603`）。
- `CreateIndexBuilder::execute` 构造并提交 `Operation::CreateIndex`（`rust/lance/src/index/create.rs:752-800`，构建在 `:778`）。

合并没有把这两个调用点改成 `CompositeOperation`，提交路径里也没有把这两种操作改写成别的变体：

- `commit_transaction_inner` 里对 `transaction` 的重写只来自 `rebase.finish_with_tagged_rewrite`
  （`rust/lance/src/io/commit.rs:2159`），而 `TransactionRebase::finish_other` 对
  `Operation::CompositeOperation(_)` 返回 `Ok(self.transaction)` 原样不动
  （`rust/lance/src/io/commit/conflict_resolver/finish.rs:52`），对 `Rewrite` 走
  `finish_rewrite`（同文件 `:574`），对 `CreateIndex` 走 `finish_create_index`（同文件 `:308`），
  三者都不改变变体。
- 合并新增的“实验性 V2 入口”在 `CommitBuilder::execute`
  （`rust/lance/src/dataset/write/commit.rs:394-403`），是这两个调用点之外的另一条入口。
- 结论：没有任何打开回收的路径会把事务变成 `CompositeOperation`。

### 1.2 没有新的产生 `_indices/{uuid}/` 的地方

在 `d8293547c..upstream/main` 的 Rust diff 里搜 `indices_dir()`、`Uuid::new_v4` 和
`build_tagged_frag_reuse_entry`，新增的 `_indices/` 写点只有一个：

| 新写点 | uuid 来源 | 是否进入候选集 |
| --- | --- | --- |
| `spill_frag_reuse_history`（`rust/lance/src/index/frag_reuse.rs:2336-2365`，写 `_indices/{uuid}/details.binpb`） | 条目 uuid 由 action 路径的 `rust/lance-table/src/transaction/action/apply/frag_reuse_history.rs:200`（`Uuid::new_v4()`）在本调用内 mint | 只在 `Operation::CompositeOperation` 上触发（`finish_built_manifest`，`rust/lance/src/io/commit.rs:1758-1761`），两条回收路径不会走到，因此也不进候选集 |

其余命中都是测试代码（`add_index_segment.rs`、`adjust_index_coverage.rs`、
`drop_index.rs`、`test_support.rs`、`proto.rs`、`dataset_transactions.rs` 的测试模块），
以及 clone 时重定位 FRI 条目的 `rust/lance/src/index/frag_reuse.rs:2680`（不在两条回收路径上）。
`rust/lance/src/index/create.rs` 的合并 diff 全部落在测试模块内。

结论：合并没有新增进入候选集的“非本次调用生成”的 uuid；`spill_frag_reuse_history` 是一个新的
漏删点（记入第 8 节），但不进入候选集。

## 2. 改动 1 的三项确认

改动只动 `commit_transaction_inner`：在 `tagged_rewrite = assembly;` 之前把
`assembly.entry.uuid` 加进 `minted.uuids`，注释改成同时覆盖 rebase 重写的索引和 tagged 条目
（`rust/lance/src/io/commit.rs:2160-2171`）。

1. 进入重试循环前 `tagged_rewrite` 的初值是 `None`（`rust/lance/src/io/commit.rs:2054`），
   所以没有“初始条目也写目录”的情况，也就没有需要额外收集的 uuid。
2. `TaggedRewriteAssembly::entry.uuid` 永远来自本次调用：
   `finish_rewrite` 在 `rust/lance/src/io/commit/conflict_resolver/finish.rs:687` 构造 assembly，
   条目来自 `build_frag_reuse_rewrite_entry` → `build_tagged_frag_reuse_entry`
   （`rust/lance/src/index/frag_reuse.rs:2100`），后者的 uuid 是 `Uuid::new_v4()`
   （同文件 `:2241`）。仓库里只有这一处生产代码构造 `TaggedRewriteAssembly::new`
   （其余是 `lance-table` 里的测试字面量），也没有任何路径把已提交条目的 uuid 装进 assembly。
3. `build_tagged_frag_reuse_entry` 注释里说的 row-map 文件目录是 `<base>/_fri/<map_id>/`：
   常量 `FRAG_REUSE_DIR = "_fri"`（`rust/lance/src/dataset.rs:201`），读取路径见
   `rust/lance/src/index/frag_reuse.rs:2769-2771`。它们不在 `_indices/` 下，也不是由
   compaction 写的：仓库里写 row map 的代码（`RowMapWriter`，`rust/lance-index/src/frag_reuse/row_map.rs`
   与 `stable_partition.rs`）目前只出现在测试里。只报告，不处理。

## 3. 改动 2 的三项确认

改动只动 `execute_multi_segment_fmindex` 里的两处提交
（`rust/lance/src/index/create.rs:958` 与 `:1049`），换成
`apply_commit_reclaiming_minted_index_dirs`，参数不变，不加注释。

1. 两条路径都不读 `self.index_uuid`。该字段只在 `execute_uncommitted_impl` 里使用
   （`rust/lance/src/index/create.rs:449`、`:452`，以及单段路径的 `:762`）。因此调用方传了
   `index_uuid` 又走到多段路径时，这个 uuid 被**静默忽略**，不会报错：每条路径都用
   `Uuid::new_v4()` 给每个段生成新 uuid（`:904`、`:988`），提交的是这些新 uuid。
2. 被提交事务的 `new_indices` 只含本次调用生成的段：它来自
   `build_index_metadata_from_segments`（`:935-938`、`:1020-1023`），输入只有循环里刚构造的
   `segment_metadatas`。被 `replace` 移除的旧同名段只进 `removed_indices`
   （`:938-945`、`:1029-1035`），而 `minted_index_uuids` 对 `CreateIndex` 只看 `new_indices`
   （`rust/lance/src/io/commit.rs:1939-1943`）。
3. 每条路径都是一次提交：函数内每个分支只有一处 `apply_commit*`，没有“先提交一部分段”的
   中间提交，因此不存在“后一次失败时前一次已提交的段”的情况。

## 4. 两个新测试

都存在既有测试文件里，都覆盖了一条新路径。

### 4.1 tagged FRI 的 rebase 溢出目录

`dataset::optimize::tests::commit::test_tagged_rebase_details_dir_reclaimed_after_verified_loss`
（`rust/lance/src/dataset/optimize/tests/commit.rs`）。

构造方式：

- 用既有 `reclaim_fixture` 建一个 4 fragment、带一个 BTree 索引的表。
- `install_external_tagged_history` 把 tagged 历史装成“详情已经溢出”的形状：
  `padding_reuse_versions` 生成 5000 组左右的 padding 组，全部放进**同一个** version
  （tagged 历史拒绝重复时间戳），编码成 `InlineContent` 后确认超过
  `FRAG_REUSE_INLINE_DETAILS_LIMIT`（204,800 字节），再用 `build_tagged_frag_reuse_entry`
  生成条目、置上 `FLAG_FRAGMENT_REUSE_INDEX` 并用 `persist_fixture` 写进 manifest。
  注意 `inline_padding_capacity` 量的是“每个 version 一组”的编码，装进单个 version 后编码更小，
  所以这里多取 1,000 组，代码注释写明了原因。
- 用 `RaceBeforeRewrite` 注入两次故障：第一次 `Race::Append`（一次不冲突的 append，让
  rewrite 的 manifest 写冲突并触发 rebase），第二次 `Race::Reject`（直接返回 I/O 错误，
  使提交核实为未落地）。断言 handler 的两次 race 都被消费。
- 断言：`_indices/` 目录集合与故障注入前完全一致（rebase 写出的两个 `details.binpb` 目录都被
  回收、已安装历史的目录保留），`details.binpb` 目录集合也不变，调用方拿到原始错误
  `injected rewrite commit failure`。

没有用交接单里的退路（不需要“只断言 uuid 进了候选集”），端到端构造成功；耗时约 0.6 秒。

`RaceBeforeRewrite` 是本轮唯一新增的测试支撑：加一个 `Race::Reject` 变体，并把
`is_version_not_found_definitive` 覆写为 `true`。后者是必要的：该 handler 的所有真实写入都
交给内置 `ConditionalPutCommitHandler`，其“版本不存在”本来就是确定性的；不覆写时默认
`false`，未落地的写会被判为 `Unknown`，回收按设计保持关闭。既有测试不依赖这个默认值——它们
要么用内置 handler 的冲突路径（判定为 `Foreign`），要么用 `AmbiguousCommitHandler`。

### 4.2 多段 FM-Index 被抢占

`index::create::tests::test_concurrent_multi_segment_fmindex_reclaims_segment_dirs`
（`rust/lance/src/index/create.rs`）。

构造方式：两个句柄 checkout 同一版本，`num_segments=2` 的整表 FM-Index 构建，同名
`text_idx`；先提交的一方留下两个段目录，后提交的一方被并发 `CreateIndex` 抢占。断言：

- 错误是 `RetryableCommitConflict`，文案含
  `CreateIndex transaction was preempted by concurrent transaction CreateIndex`；
- `_indices/` 目录集合与抢占前一致（被拒构建的两个段目录被回收，胜者的两个保留）；
- 胜者的索引仍是 2 个段。

覆盖的是**训练过**的那条路径（`:1049`）。另一条（`!train` 或没有 fragment 的定义式路径，`:958`）
没有单独覆盖：该路径在测试里不落地任何段文件，目录集合的断言对它恒成立，钉不住变异；
`ScalarIndexParams` 的 `train(false)` 变体因此没有写进用例。耗时约 0.2 秒。

## 5. 变异检查

11 项全部在 fix tip `98f701cc4` 上应用、运行、还原，未提交。逐项输出见
`results/mutations-98f701cc4.log`。

| # | 被去掉/反转的守卫 | 必须失败的测试 | 结果 |
| --- | --- | --- | --- |
| 1 | 外层清理调用 | `test_delete_conflict_reclaims_remapped_index_dir`、`...::case_1_verified_absent`、`case_1_drop_indexed`、`case_3_cast_indexed` | 4 个全部失败 |
| 2 | `!has_unverified_write` | `...::case_4_landed_then_index_dropped`、`...::case_5_unknown_then_index_dropped` | 2 个全部失败 |
| 3 | 清理放在重试循环之后（移进 `Foreign \| Absent` 分支） | `test_retry_after_concurrent_append_keeps_index_dirs` | 失败 |
| 4 | `CommitBuilder::execute` 的 `ReclaimOnLoss::None` | `test_failed_commit_keeps_caller_owned_index_segment` | 失败 |
| 5 | `new_id != old_id` 过滤 | `test_minted_index_uuids_collects_only_new_ids` | 失败 |
| 6 | 调用方命名目录的分支（去掉） | `case_6_drop_caller_named_uuid` | 失败 |
| 7 | 调用方命名目录的分支（取反） | `case_6`、`case_1_drop_indexed`、`case_3_cast_indexed`、`test_concurrent_create_index_same_name_returns_retryable_conflict` | 4 个全部失败 |
| 8 | `IndexRemapper::creates_fresh_index_ids` 默认值 | `test_custom_remapper_index_dir_survives_preemption` | 失败 |
| 9 | `DatasetIndexRemapper::creates_fresh_index_ids` 覆写 | `test_delete_conflict_reclaims_remapped_index_dir`、`...::case_1_verified_absent` | 2 个全部失败 |
| 10 | 把 assembly 的 uuid 加入候选集 | `test_tagged_rebase_details_dir_reclaimed_after_verified_loss` | 失败（目录集合多出两个 rebase 目录） |
| 11 | 多段 FM-Index 覆盖的那条路径改回 `apply_commit` | `test_concurrent_multi_segment_fmindex_reclaims_segment_dirs` | 失败（目录集合多出两个段目录） |

## 6. 验证命令与结果

在 macOS arm64 上执行，原始输出见 `results/checks-98f701cc4.log`、
`results/full-test-98f701cc4.log`。

| 命令 | 结果 |
| --- | --- |
| `cargo fmt --all -- --check` | 通过（exit 0） |
| `cargo clippy --all --tests --benches -- -D warnings` | 失败，只有 `rust/lance-encoding/src/encodings/physical/byte_stream_split.rs` 的 2 处 `unreachable expression`（`-D unreachable-code` 导致），与交接单预期一致 |
| `cargo clippy --all --tests --benches -- -D warnings -A unreachable-code` | 通过（exit 0） |
| `cargo test -p lance` | 通过：11,380 通过、0 失败、31 忽略（lib 11,051 + 9 忽略；其余 10 个集成二进制 329 通过 + 22 忽略） |
| `RUSTDOCFLAGS="-D warnings" cargo doc -p lance --no-deps` | 通过（exit 0） |
| `git diff upstream/main HEAD \| grep '^+' \| grep -E "\b([TCP][0-9]+'?)\b"` | 输出为空，没有合法命中需要解释 |

全量测试与复现都以 fix tip `98f701cc4` 为被测提交；全量测试在 fix 分支上直接运行，
`review` 分支合并后的 Rust 内容与之相同。

复现（`review/issue-7207/repro/apply.sh`）在一次性的 detached worktree 里对 `98f701cc4` 运行，
用完即删；原始输出见 `results/repro-98f701cc4.log`：

```text
ORPHANS after 20 failed compaction commits: dirs=0 bytes=0
test io::commit::repro_7207::repro_7207_leaked_index_dirs ... ok
```

没有测试失败，因此不需要在纯 `upstream/main` 上重跑归类。

## 7. 分离检查与分支 SHA

按 skill 附录 A 的脚本执行。合并提交之后、写 review 材料之前跑一次（本地、提交前）：

```text
$ bash check_separation.sh fix/7207-failed-commit-index-cleanup review/7207-failed-commit-index-cleanup 7207
pure:   fix/7207-failed-commit-index-cleanup -> 98f701cc4bd409c40f938aa74913f443625108a8
review: review/7207-failed-commit-index-cleanup -> e8ab5f68ad466db6f8197330b7ae8cef9eb89a9f
review material path: review/issue-7207/

PASS [pure-clean]: pure ref contains no review/issue-*/ files
PASS [up-to-date]: pure commit is an ancestor of review
PASS [tree-diff]: all differences are under review/issue-7207/
PASS [commit-split]: every review-side commit touches only review/issue-7207/

RESULT: separated
```

提交之后、推送之前再跑一次（本地、提交后）：

```text
$ bash check_separation.sh fix/7207-failed-commit-index-cleanup review/7207-failed-commit-index-cleanup 7207
pure:   fix/7207-failed-commit-index-cleanup -> 98f701cc4bd409c40f938aa74913f443625108a8
review: review/7207-failed-commit-index-cleanup -> 07c4af27cb7964c764aaa5b1e0e145ae105dc9a7
review material path: review/issue-7207/

PASS [pure-clean]: pure ref contains no review/issue-*/ files
PASS [up-to-date]: pure commit is an ancestor of review
PASS [tree-diff]: all differences are under review/issue-7207/
PASS [commit-split]: every review-side commit touches only review/issue-7207/

RESULT: separated
```

推送后对远端引用复跑一次：

```text
$ bash check_separation.sh origin/fix/7207-failed-commit-index-cleanup origin/review/7207-failed-commit-index-cleanup 7207
pure:   origin/fix/7207-failed-commit-index-cleanup -> 98f701cc4bd409c40f938aa74913f443625108a8
review: origin/review/7207-failed-commit-index-cleanup -> 07c4af27cb7964c764aaa5b1e0e145ae105dc9a7
review material path: review/issue-7207/

PASS [pure-clean]: pure ref contains no review/issue-*/ files
PASS [up-to-date]: pure commit is an ancestor of review
PASS [tree-diff]: all differences are under review/issue-7207/
PASS [commit-split]: every review-side commit touches only review/issue-7207/

RESULT: separated
```

另加的三条命令（提交前）：

```text
$ git ls-tree -r --name-only fix/7207-failed-commit-index-cleanup | grep '^review/issue-'
（输出为空）

$ git merge-base --is-ancestor fix/7207-failed-commit-index-cleanup review/7207-failed-commit-index-cleanup
（退出码 0）

$ git diff --name-only fix/... review/... | grep -v '^review/issue-7207/'
（输出为空）
```

分支 SHA：

| Ref | 本地 | 远端 `easyrev/lance` |
| --- | --- | --- |
| `fix/7207-failed-commit-index-cleanup` | `98f701cc4bd409c40f938aa74913f443625108a8` | `98f701cc4bd409c40f938aa74913f443625108a8` |
| `review/7207-failed-commit-index-cleanup`（分离检查时） | `07c4af27cb7964c764aaa5b1e0e145ae105dc9a7` | `07c4af27cb7964c764aaa5b1e0e145ae105dc9a7` |
| `upstream/main`（本轮合并用） | `134c2bf954` | — |

两个分支都是普通 push（`794031b87..98f701cc4` 与 `fd26fbf0d..07c4af27c`），没有 rebase、
没有 amend、没有强推。review 分支的 tip 包含本报告，报告无法预知自己这个提交的 SHA；分离检查
记录的是它的父提交 `07c4af27c`（只改本报告与 README 的提交在其上），推送后以 `git ls-remote`
核对的结果为准，做法与上一轮相同。

## 8. 新发现的缺口与拿不准的地方

1. **action 路径的 FRI 溢出不进候选集。** `spill_frag_reuse_history`
   （`rust/lance/src/index/frag_reuse.rs:2336`）在 `Operation::CompositeOperation` 的提交里写
   `_indices/{uuid}/details.binpb`，uuid 由本次调用 mint，但 `minted_index_uuids` 对
   `CompositeOperation` 返回空。当前没有回收路径会走到它（见 1.2），所以不修，但将来若把
   `CompositeOperation` 的调用点 opt-in，必须同时补上这个 uuid。
2. **row map 还没有写入方。** `build_tagged_frag_reuse_entry` 的注释描述的 `<base>/_fri/<map_id>/`
   目录，目前只有测试在写；生产 compaction 不写。若后续 PR 加了写入方，这套目录不在 `_indices/`
   下，回收逻辑需要另议。
3. **未覆盖的多段定义式路径。** `!train` / 无 fragment 的那条 FM-Index 路径换成了回收调用，
   但没有能钉住它的测试（见 4.2 的理由）。变异检查只覆盖了训练过的那条。
4. **`RaceBeforeRewrite` 判定口径的改动。** 为了让“未落地的写”被核实为 `Absent`，给测试
   handler 加了 `is_version_not_found_definitive() -> true`。它对本轮之前的既有测试没有行为影响
   （那些用例要么走内置 handler 的冲突路径，要么用 `AmbiguousCommitHandler`），但这确实改了一处
   共享测试支撑，逐条核对的结论写在 4.1。
5. **review 材料的提交拆分。** 交接单要求 `README.md`、`reports/`、`results/` 分别更新。三类改动
   在本地都改好后，挂钩子重跑时一次性暂存成了一个提交 `07c4af27c`，没有拆成三个；内容与分离检查
   不受影响（只触及 `review/issue-7207/`），但比约定的提交粒度粗。此后按约定用单独提交补记远端
   分离检查的结果。
6. **计划编号检查需要跑在 fix 分支上。** 交接单里的 `git diff upstream/main HEAD` 若在 review
   分支上执行，会命中 `review/issue-7207/` 里引述旧编号的文档；这些文档是 review 材料，不属于
   代码/提交信息。fix 分支上的输出为空（见第 6 节）。
