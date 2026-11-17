# #7207 补充交接单执行报告：在 §7 第一个停止条件停下

- 分支：`fix/7207-failed-commit-index-cleanup`，HEAD 仍为 `ab6f31589`，工作树无改动（`output/`、`research/` 为未跟踪目录）
- 实现基线：`d8293547c`；核对时 `upstream/main` = `ff6ecbdbb`（见 §5）
- 本报告只含只读核对的结论；**没有**实施改动 A/B/T10，没有新提交，没有 push，没有 PR，没有 GitHub 评论

## 0. 结论

**命中 §7 停止条件 1**：候选 uuid 里存在改动 A 之外"不是本次调用生成"的来源 —— 调用方自定义的 `IndexRemapper` 可以通过 `compact_files` / `commit_compaction` 把任意 `new_id` 塞进 `Operation::Rewrite.rewritten_indices[]`，而 `commit_rewrites` 无条件打开了 `ReclaimOnLoss::MintedIndexDirs`。这与改动 A 要修的 `index_uuid` 属于同一类所有权漏洞，但修复点落在 C8 五个文件之外，因此按 §7 停止，交还人工决定。

附带两条核对结论（也影响原报告，见 §4）：

1. §6.2 的原报告缺口 5 表述不成立：tagged 组装在 rebase 落盘时**会**写 `_indices/{uuid}/details.binpb`，且该 uuid **不在** 事务的 `Operation` 里，因此现有清理既不会回收它、也不需要保护它 —— 那是一个真实的泄漏，不是"无泄漏"。
2. §6.3 基线前进 3 个提交，其中 `279bd588e`（#10767）触及 `rust/lance/src/index/create.rs`，但两个 hunk 全部落在 `mod tests` 内，与改动 A 的落点（`execute`，752–796 行）不冲突。

停止条件逐条过了一遍，只命中第 1 条：`gh pr list --search 7207` 在 upstream 只返回已关闭的 #8118，没有覆盖 #7207 的新 PR。

## 1. 环境

本机（即本次核对执行环境）：

```
$ uname -m
arm64
$ rustc --version
rustc 1.98.1 (48a229cea 2026-09-01)
```

即 **macOS aarch64**，不满足 §5 要求的 Linux x86_64，所以 §5 的命令一条也没有当作"通过"来跑。环境另况：

- `docker` 二进制在，但 OrbStack daemon 未运行（`~/.orbstack/run/docker.sock` 不存在）。
- `ssh vmiss` 可达，`uname -m` 为 `x86_64`，但该机没有 `rustc`，也没有 Lance 检出目录 —— 要在上面跑 §5 需要先装工具链并拉仓库（另加一次完整编译）。
- `ssh lance-ecs`（阿里云 ECS）当前拒绝连接（`Connection closed by 47.117.80.3 port 22`）。

也就是说：即便没有命中停止条件，§5 也必须在 x86_64 Linux 上先把环境搭好才能如实执行；上一轮报告只跑了四个 `--lib` 过滤器和带 `-A unreachable-code` 的 clippy，不能替代 §5 的全量要求。

## 2. §6.1 候选 uuid 的全部来源

`minted_index_uuids`（`rust/lance/src/io/commit.rs:1887`）只看两个变体，且只有两处调用点打开了回收（`rust/lance/src/index/create.rs:790`、`rust/lance/src/dataset/optimize/commit.rs:617`）。

### 2.1 `Operation::CreateIndex.new_indices[].uuid`（过滤 `base_id.is_none()`）

| # | 赋值来源 | 是否必然由本次调用内的 `Uuid::new_v4()` 生成 | 是否进得了回收路径 |
| --- | --- | --- | --- |
| 1 | `index/create.rs:452` `let index_id = self.index_uuid.unwrap_or_else(Uuid::new_v4);` | **否**：`CreateIndexBuilder::index_uuid()`（`create.rs:151`）由调用方指定，Python/Java 也暴露该参数 | 是；正是改动 A 要处理的一处 |
| 2 | `index/create.rs:453` `let mut output_index_uuid = index_id;` → `create.rs:622` `output_index_uuid = segment_uuid;`；`segment_uuid` 来自 `build_distributed_vector_index`（`index/vector.rs:852`）里的 `let segment_uuid = uuid;`（`vector.rs:883`），而 `uuid` 就是传进去的 `index_id` | 与 #1 同源：调用方给了 uuid 就是调用方的，没给就是本调用的 | 是；不是独立来源，跟 #1 一起被改动 A 覆盖 |
| 3 | `index/create.rs:898`、`create.rs:978`（`execute_multi_segment_fmindex` 的每个分段）`Uuid::new_v4()` | 是 | **否**：该路径在 `create.rs:952` / `create.rs:1039` 用普通 `apply_commit` |
| 4 | 其它 `Operation::CreateIndex` 生产者：`index/append.rs`、`index/optimize.rs` 等 | 各自内联 uuid，或复用已有段 | **否**：都走普通 `apply_commit`（`index/append.rs:2638/2660`、`index/optimize.rs:1634/1733`） |

结论：进得了回收路径的 `CreateIndex` 候选只有 #1/#2，且是同源的 `index_id` —— 改动 A 的守卫对它成立。

### 2.2 `Operation::Rewrite.rewritten_indices[].new_id`（过滤 `new_id != old_id`）

`rewritten_indices` 由 `commit_rewrites` 从 `IndexRemapper::remap_indices_with_context` 的返回值直接拷贝（`dataset/optimize/commit.rs:450-462`，`new_id: rewritten.new_id`）。各实现：

| # | 实现 | 来源 | 是否必然由本次调用内的 `Uuid::new_v4()` 生成 |
| --- | --- | --- | --- |
| 5 | `DatasetIndexRemapper`（`dataset/index.rs:279`）→ 标量/通用单段 remap | `index/remap.rs:143` `let new_id = Uuid::new_v4();` | 是 |
| 6 | 同上 → 向量段原子合并 | `index/vector/ivf.rs:3140` `let segment_uuid = Uuid::new_v4();`（`merge_remapped_segments` → `merge_segments_inner`；`ivf.rs:3113-3115` 保证 `segments.len() >= 2`，不会落回 `segments[0]`） | 是 |
| 7 | 同上 → `RemapResult::Keep` | `dataset/index.rs:158-164` `new_id: id`（= `old_id`） | 是旧 id，被 `new_id != old_id` 过滤掉 |
| 8 | `IgnoreRemap`（`dataset/optimize/remapping.rs:105`） | 返回空 Vec | 不产生候选 |
| 9 | **调用方自定义的 `IndexRemapper`** | 公开 trait：`dataset/optimize/remapping.rs:62` `pub trait IndexRemapper`，`remap_indices_with_context`（`remapping.rs:72-84`，默认转发 `remap_indices`）；入口 `compact_files(dataset, options, remap_options: Option<Arc<dyn IndexRemapperOptions>>)`（`dataset/optimize.rs:133`）与 `commit_compaction(..., remap_options: Arc<dyn IndexRemapperOptions>, ...)`（`dataset/optimize/commit.rs:138`，经 `dataset/optimize.rs:102` 公开重导出）；`commit_rewrites` 在 `commit.rs:238-241` 用它建 remapper | **否**：`new_id` 由调用方的代码决定，不保证是本调用内的 `Uuid::new_v4()`（确定性 id、按内容哈希缓存的 id、或本调用之前就已写好的 id 都能通过） |

### 2.3 `Operation::Rewrite.frag_reuse_index.uuid`（不过滤）

| # | 赋值来源 | 是否必然由本次调用内的 `Uuid::new_v4()` 生成 | 备注 |
| --- | --- | --- | --- |
| 10 | `index/frag_reuse.rs:908` `build_new_frag_reuse_index` → `frag_reuse.rs:966` `build_frag_reuse_index_metadata` 里的 `Uuid::new_v4()` | 是 | 内容超过 200 KiB（`frag_reuse.rs:2302`）时写 `_indices/{uuid}/details.binpb`（`966-980`） |
| 11 | `index/frag_reuse.rs:1434` `frag_reuse_entry_appending`（调用点 `dataset/optimize/commit.rs:572`）→ `frag_reuse.rs:1498` `Uuid::new_v4()` | 是 | 纯内联，不写文件 |
| 12 | `index/frag_reuse.rs:2235` `build_tagged_frag_reuse_entry` → `frag_reuse.rs:2240` `Uuid::new_v4()`，由 rebase 的 `build_frag_reuse_rewrite_entry`（`frag_reuse.rs:1720`）经 `io/commit/conflict_resolver/finish.rs:668-669` 调用 | 是（uuid 确实在本调用内生成） | 超过 200 KiB 时写 `_indices/{uuid}/details.binpb`（`frag_reuse.rs:2274-2296`），但该 uuid **不在** `Operation` 里，见 §4 |

### 2.4 判定

除改动 A 处理的 `index_uuid` 之外，**只有 #9 一个来源不是"本次调用生成"的 uuid**，而它恰好落在 `commit_rewrites` 无条件打开的回收路径上。按 §7 第一条停止条件，停止改代码。

一个可佐证的细节：原计划 C3 的前提是"compaction 的目录是本调用内 mint 的"，对内置 remapper 成立；对调用方自定义的 remapper 不成立，所以这个洞和 `index_uuid` 是同一类问题，而不是"另一种缺口"。

## 3. 停止理由与修复方向的评估

### 3.1 这个洞会怎么伤人（诚实分级）

要真正删错目录，需要同时满足：

1. 调用方给 `compact_files` / `commit_compaction` 传了自定义 `IndexRemapperOptions`（Python/Java 不会：`python/src/dataset/optimize.rs:572` 与 `java/lance-jni/src/blocking_dataset/maintenance.rs:27` 都传 `None`，走内置 `DatasetIndexRemapperOptions`）；且
2. 该 remapper 返回的 `new_id` 不是"本调用内独占 mint 的新 id"（确定性/内容寻址/复用上次结果）；且
3. 这次提交被 `verify_commit_outcome` 判为 `Foreign`/`Absent`（正是 #7207 里 DELETE 抢占 Rewrite 的常见场景）；且
4. 之后那次调用按同一批 id 复用/重放，而没有重新写这些目录。

满足 3 就会删掉调用方拥有的目录；满足 4 之后就可能让 manifest 引用一个已不存在的 `_indices/{uuid}`。这不是理论构造：内容寻址式 remapper（同样的源 → 同样的 id，已存在就跳过重写）是很自然的实现方式，第 2 条会直接命中。

名字上它也确实不是"本调用生成"：`new_id` 的取值权在调用方的 `IndexRemapper` 手里，跟 `.index_uuid(...)` 一模一样。

### 3.2 修复点为什么不在 C8 五个文件内

- 正确的修法是在 `IndexRemapperOptions`（或 `IndexRemapper`）上加一个显式声明，例如 `fn mints_fresh_index_ids(&self) -> bool { false }`，只有 `DatasetIndexRemapperOptions` 返回 `true`；`commit_rewrites`（`dataset/optimize/commit.rs`，在 C8 内）据此决定传 `MintedIndexDirs` 还是 `None`。
  - 这要改 `rust/lance/src/dataset/optimize/remapping.rs`（trait 定义 + 默认 `false`）和 `rust/lance/src/dataset/index.rs`（`DatasetIndexRemapperOptions` 实现），**两者都在 C8 之外**。
- C8 内唯一的"就地"办法是复用已有的 `supports_vector_segment_replacement()`（`remapping.rs:88-91`，`DatasetIndexRemapperOptions` 返回 `true`，`dataset/index.rs:58-60`）当代理。**不推荐**：语义是"能否原子替换兼容向量段"，与所有权无关；恰好也想原子替换、但 id 由自己决定的第三方 remapper 会返回 `true`，于是被误开回收，问题原样保留，还多一处隐式耦合。
- 量级：真正修法大约 +8～12 行非测试代码，239 + 12 ≈ 251 行，会顶到 §2 的 250 行上限，需要一并重新评估预算。

### 3.3 与"已知缺口"的区别

原报告缺口 1（`CommitBuilder` 等调用方自带事务）是"明知调用方拥有、所以不回收"；这里是"以为是自己 mint 的、其实调用方拥有，却照样回收"，属于守卫本身的洞。这就是 §7 第 1 条要拦的东西，不能降级成缺口记录。

## 4. §6.2 tagged fragment reuse 是否写目录：会写，而且 uuid 不在 `Operation` 里

原报告缺口 5 写的是"tagged fragment reuse 组装条目：不写 uuid 目录，无泄漏"。逐点核对：

1. **`frag_reuse_entry_appending` 本身不写文件**。`index/frag_reuse.rs:1434-1505`：只拼接 content、`Uuid::new_v4()`（1498）后返回 `index_version: 1`、`files: None` 的内联条目；函数的 doc comment 明说"返回的条目无论多大都保持内联，是内存意图，永远不是落进 manifest 的条目"，把落盘交给提交路径。
2. **提交路径确实会写 `_indices/{uuid}/`**。tagged 表在 rebase 时走 `finish_rewrite`（`io/commit/conflict_resolver/finish.rs:569`）→ `build_frag_reuse_rewrite_entry`（`finish.rs:668-669`）→ `build_tagged_frag_reuse_entry`（`index/frag_reuse.rs:2235`）→ `encode_tagged_frag_reuse_details`（`frag_reuse.rs:2274-2296`）：content 超过 `FRAG_REUSE_INLINE_DETAILS_LIMIT = 204800`（`frag_reuse.rs:2302`）时写 `_indices/{index_id}/details.binpb`。
3. **这个 uuid 不在事务的 `Operation` 里**。`build_frag_reuse_rewrite_entry` 的返回值不写回 `Operation::Rewrite.frag_reuse_index`，而是包成 `TaggedRewriteAssembly`，以 `FragReuseUpdate::Rewrite(assembly)` 这条**内存旁路**继续传递（`lance-table/src/transaction/prepare.rs:26-42`；`rust/lance/src/io/commit.rs:2119-2126` 保存、`:2189-2193` 传给 `prepare_attempt`；`io/commit.rs:1774` → `Transaction::prepare_indices`），最终在 `lance-table/src/transaction/manifest_build.rs:1354-1385` 用 `assembly.entry` 覆盖 manifest 里的条目。对比 v0 路径：rebase 是 `*new_fri = new_frag_reuse_index_meta;`（`finish.rs:765-773`）写回 operation，所以 v0 的 rebase uuid 会进 `Operation`、会被 `io/commit.rs:2119-2126` 那次"rebase 后重新采集"收进来 —— tagged 不会。
4. 因此 `minted_index_uuids` 看不到 Y，`cleanup_minted_index_dirs` 既不会回收它，也谈不上保护它。

结论（缺口 5 应改成）：**tagged 组装（首轮 `frag_reuse_entry_appending`）不写目录；但 tagged 表在 rebase 落盘时每次都会 mint 一个新 uuid 并在超过 200 KiB 时写 `_indices/{uuid}/details.binpb`，该 uuid 不在 `Operation` 内，既不会被失败路径回收（每次冲突重试各留一个），也不会被成功路径回收。** 这是"泄漏"而不是"删错"，所以不触发 §7 的停止条件，但它使原报告 §2 那句"实现因此在每次 `transaction = rebased` 之后重新采集"对 tagged 路径不成立，应一并更正。

顺带说明：这也让原报告缺口 2 的范围变大 —— 缺口 2 只写了 v0 的 `build_frag_reuse_index_metadata`；tagged 的 `build_tagged_frag_reuse_entry` 是同一形状且更彻底（连候选集都进不去）。

## 5. §6.3 基线漂移

`upstream/main` 相对 `d8293547c` 前进 **3 个提交**（`git fetch upstream` 后）：

| 提交 | 标题 | 是否触及 C8 五个文件 |
| --- | --- | --- |
| `279bd588e` | `feat(index): report the build stages of scalar indices (#10767)` | **是**：`rust/lance/src/index/create.rs`（+331/−…），另触及 `rust/lance-index/src/progress.rs` 等 |
| `a5e0dec98` | `fix(fts): use the shared corpus scorer on tables with deleted rows (#11139)` | 否（`dataset/scanner/fts.rs`、`dataset/tests/dataset_index.rs`） |
| `ff6ecbdbb` | `chore: release beta version 15.0.0-beta.24` | 否（版本/lockfile） |

`create.rs` 的两个 hunk 头分别是 `@@ -1219,9 +1219,10 @@ mod tests` 和 `@@ -2161,6 +2162,334 @@ mod tests`，都在 `mod tests` 内（新增 `IoRecordingProgress` 等进度断言测试），改动 A 的落点（`CreateIndexBuilder::execute`，约 781–795 行）不受影响。只报告，不 rebase。

## 6. 未执行的部分

- **改动 A / 改动 B / T10**：未实施（§7 停止条件 1）。因此也没有 diff 摘要、没有新的非测试净增行数、没有变异 6/7 的结果。
- **§5 的四条命令**：未执行。本机是 macOS arm64（§1），且按 §7 已停止，跑测试没有意义；不把任何命令写成"通过"。
- T10 的静态可行性（供恢复时参考）：`ensure_index_uuid_allowed`（`index/create.rs:1157-1204`）只在 `index_uuid.is_some()` **且** `fragments` 非空 **且** 类型属于 BTree/RTree/NGram/LabelList 时拒绝；Bitmap + 不传 `fragments` + `.index_uuid(...)` 是允许的，目录确实写在 `_indices/{uuid}`（`build_scalar_index` → `LanceIndexStore::from_dataset_for_new`，`index/scalar.rs:558`、`dataset/index.rs:398-405`），`index_dir_names`（`index/create.rs:1254`）取的是目录名。所以"扩展到 `test_create_index_after_concurrent_schema_change` 的 caller-uuid case、断言 `dirs_before ∪ {uuid}`"可以构造出来；但按 doc，现有 T7 的断言不动，需要新增一个 case 参数并在冲突分支里分支到两种期望集合 —— 这点在恢复时要先跟人确认写法（见 §7 选项 B）。

## 7. 需要人工决定的三选一

1. **按 §7 收工**（本报告即交付）：把 §2.2 #9 记入"已知缺口"，另开 issue/后续 PR 处理；本分支不再追加改动。
2. **授权把守卫扩到 remapper**：加 `IndexRemapperOptions::mints_fresh_index_ids()`（默认 `false`，`DatasetIndexRemapperOptions` 为 `true`），`commit_rewrites` 据此 opt-in；接受改动 `remapping.rs` / `dataset/index.rs`（C8 之外，约 +8～12 行，总量约 251 行，需重新评估 250 行上限），然后按本单做 A/B/T10 并跑 §5。
3. **先只做 A/B/T10、把 #9 记为缺口**：可以在本单范围内完成，但等于明知守卫有同类洞还先合并；只有当 #9 被判为"第三方 remapper 自己担责"时才成立，不建议默认这样。

§4 的缺口 5 更正与 §2 的 §6.1 结论无论选哪个选项都应写进最终报告。

## 8. 假设与不确定处

- §2.2 #9 的"不是本次调用生成"按所有权判读：uuid 的取值权在调用方代码里，即使目录文件是本调用内写的，也不构成"我们的目录"。若人工认为"调用方 remapper 在提交调用内写的就是本次调用生成"，则停止条件 1 不成立，可走选项 3。
- 我按静态代码判定 tagged 组装 uuid 不进 `Operation`（§4.3），依据是 `finish.rs:688` 原样返回 `self.transaction` 且 `io/commit.rs:2119-2126` 只对 `transaction.operation` 重新采集；未写复现用例验证（那样等于开始改代码）。
- §4 的泄漏量没有实测，只用代码路径确认"会写、且不在候选集里"。
- `vmiss` 上跑 §5 的成本未评估（无工具链、无检出）。

## 附：核对用到的关键行号

```
rust/lance/src/io/commit.rs:235-241        cleanup_minted_index_dirs 的 doc comment（改动 B 的落点）
rust/lance/src/io/commit.rs:1887-1906      minted_index_uuids
rust/lance/src/io/commit.rs:1921-1945      commit_transaction 的采集与清理门
rust/lance/src/io/commit.rs:2119-2126      rebase 后重新采集
rust/lance/src/io/commit.rs:2189-2193      FragReuseUpdate::Rewrite 旁路
rust/lance/src/index/create.rs:445-453     ensure_index_uuid_allowed + index_id
rust/lance/src/index/create.rs:611-622     distributed vector output_index_uuid
rust/lance/src/index/create.rs:752-796     改动 A 的落点（execute 的 apply_commit）
rust/lance/src/index/create.rs:1254        index_dir_names
rust/lance/src/index/create.rs:1676-1780   test_create_index_after_concurrent_schema_change（T7）
rust/lance/src/dataset/optimize/remapping.rs:62-84   IndexRemapper / remap_indices_with_context
rust/lance/src/dataset/index.rs:57-75      DatasetIndexRemapperOptions
rust/lance/src/dataset/index.rs:279        impl IndexRemapper for DatasetIndexRemapper
rust/lance/src/dataset/optimize/commit.rs:238-241   create_remapper
rust/lance/src/dataset/optimize/commit.rs:440-462   rewritten_indices 拷贝 new_id
rust/lance/src/dataset/optimize/commit.rs:616-622   回收 opt-in
rust/lance/src/index/remap.rs:143           new_id
rust/lance/src/index/vector/ivf.rs:3140    merged segment uuid
rust/lance/src/index/frag_reuse.rs:966,968-980      v0 详情 uuid + 落盘
rust/lance/src/index/frag_reuse.rs:1498    frag_reuse_entry_appending uuid（纯内联）
rust/lance/src/index/frag_reuse.rs:2240,2274-2296   tagged 条目 uuid + 落盘
rust/lance/src/io/commit/conflict_resolver/finish.rs:668-669, 688, 765-773
lance-table/src/transaction/prepare.rs:26-42
lance-table/src/transaction/manifest_build.rs:1354-1385
```
