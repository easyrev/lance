# #7207 收尾交接单：注释清理、合并验证与 review 分支重建

Nov 17, 2026 · @ma3

## 1. 范围与顺序

在 `fix/7207-failed-commit-index-cleanup`（当前 `9a49c0174`）上做开 PR 前的收尾。四项任务都不改任何逻辑和测试断言，按顺序做：

1. 任务 A：删掉注释里的计划编号（`T1`–`T11`、`C1`）。这些编号来自内部计划，上游维护者看不懂。
2. 任务 B：精简四处解释所有权的注释，只保留代码里读不出来的理由。
3. 任务 C：与最新 `upstream/main` 试合并并验证。不 rebase，不改写已推送的历史。
4. 任务 D：按 issue-branches 约定重建 `review/7207-failed-commit-index-cleanup`。

任务 A、B 合成 fix 分支上的一个新提交。不设行数上限。

## 2. 任务 A：删掉注释里的计划编号

共 10 处，全部在测试代码的注释里。行号以 `9a49c0174` 为准，按文字定位。只改列出的那一行，后续行不动。

| 文件 | 行 | 现在 | 改成 |
| --- | --- | --- | --- |
| `rust/lance/src/io/commit.rs` | 4277 | `/// T1: only directories this transaction minted are candidates. A remap` | `/// Only directories this transaction minted are candidates. A remap` |
| 同上 | 4331 | `/// T9: cleanup must re-read the latest manifest and keep a directory it` | `/// Cleanup must re-read the latest manifest and keep a directory it` |
| 同上 | 4385 | ``/// C1's `Foreign` branch: when another writer wins the target version,`` | `/// When another writer wins the target version,` |
| `rust/lance/src/dataset/optimize/tests/commit.rs` | 1275 | `/// T2 (#7207's original shape): a concurrent DELETE lands before the rewrite` | `/// The shape reported in #7207: a concurrent DELETE lands before the rewrite` |
| 同上 | 1339 | `/// T11: a caller-supplied remapper owns the ids it reports, so its directory` | `/// A caller-supplied remapper owns the ids it reports, so its directory` |
| 同上 | 1410–1411 | `/// does not reference the minted directory: only the write tracking of` / `/// C1 protects it.` | `/// does not reference the minted directory: only the unverified-write` / `/// flag protects it.` |
| 同上 | 1497 | `/// T3, T4, T5: whether the remapped index directory survives depends only on` | `/// Whether the remapped index directory survives depends only on` |
| 同上 | 1632 | `/// T6: between retries the directories must survive, because the retry reuses` | `/// Between retries the directories must survive, because the retry reuses` |
| `rust/lance/src/dataset/write/commit.rs` | 1595 | `/// T8: a caller that built an index segment and commits it itself owns` | `/// A caller that built an index segment and commits it itself owns` |
| `rust/lance/src/index/create.rs` | 1754–1755 | ``// T10: a directory the caller named through `index_uuid` is not`` / `// this call's to remove, even though the commit failed.` | 两行都删掉。下方的断言文案已经说明了这件事。 |

改完后下面的命令输出必须为空，把结果贴进报告：

```bash
git diff d8293547c HEAD | grep '^+' | grep -E "\b(T[0-9]+'?|C[1-8])\b"
```

需要过滤掉合法命中时，逐条写明理由。commit message 里同样不得出现这些编号。

## 3. 任务 B：精简四处所有权注释

原则：变量名和方法名已经说清的内容不再写成注释，只留读代码读不出来的理由。只改注释，不改任何代码行。

**1. `rust/lance/src/index/create.rs`，`CreateIndexBuilder::execute` 里 `if caller_named_index_dir` 上方的三行注释，换成一行：**

```rust
        // A caller-named directory may hold files written outside this call.
```

**2. `rust/lance/src/dataset/optimize/commit.rs`，`let reclaim_index_dirs` 上方的五行注释，换成两行：**

```rust
    // Remapped segments are the only index IDs a caller can supply here, so a
    // call without a remapper mints every directory it commits.
```

**3. `rust/lance/src/dataset/optimize/remapping.rs`，`IndexRemapper::creates_fresh_index_ids` 的 doc comment，换成：**

```rust
    /// Whether every ID in the [`RemappedIndex`]es this remapper reports is
    /// generated inside the call that reports them. When true, compaction
    /// removes those index directories once its commit is verified not to
    /// have landed, so return true only if a retry never reuses an ID.
```

这是公开 trait 的契约，必须保留。

**4. `rust/lance/src/dataset/index.rs`，`DatasetIndexRemapper` 覆写 `creates_fresh_index_ids` 上方的两行 doc comment：删掉。** 它引用了“下面两条路径”和别处的过滤器，最容易随代码变动过时。

任务 A、B 都完成后，下面的命令输出必须为空，证明只动了注释。把结果贴进报告：

```bash
git diff 9a49c0174 HEAD | grep -E '^[+-]' | grep -vE '^(\+\+\+|---)' | grep -vE '^[+-]\s*//'
```

然后跑 `cargo fmt --all -- --check` 和 `RUSTDOCFLAGS="-D warnings" cargo doc -p lance --no-deps`，都要通过。提交为一个新提交，例如 `chore: tighten comments on failed-commit index cleanup`。

## 4. 任务 C：与最新 upstream/main 试合并并验证

目的是确认这个分支合进最新的 main 之后仍然通过，而不改写 fix 分支的历史。PR 会被 squash 合并，不需要 rebase。

1. `git fetch upstream`，记录 `upstream/main` 的 SHA。
2. 在一次性 worktree 里试合并，不要在 fix 分支上直接合并：

   ```bash
   git worktree add --detach /tmp/7207-merge-check HEAD
   cd /tmp/7207-merge-check
   git merge --no-edit upstream/main
   ```
3. 有冲突就按第 6 节停下，列出冲突文件。
4. 无冲突则在该 worktree 里跑：

   ```bash
   cargo fmt --all -- --check
   cargo clippy --all --tests --benches -- -D warnings -A unreachable-code
   cargo test -p lance
   ```

   clippy 的 `-A unreachable-code` 只为放行 macOS arm64 上 `byte_stream_split.rs` 那两处预先存在的报错，上一轮已在基线上复现过。
5. 有测试失败时，在纯 `upstream/main` 上单独重跑该测试再归类：上游也失败则列为预先存在，不修；上游通过则按第 6 节停下。
6. 删除 worktree：`git worktree remove /tmp/7207-merge-check`。试合并的提交不推送、不保留。

## 5. 任务 D：按 issue-branches 约定重建 review 分支

如果当前环境有 `issue-branches` skill，调用它并以它为准；没有就按本节执行。

**目标状态（不变量）。** `review/7207-failed-commit-index-cleanup` 等于 fix 分支的最新提交，加上若干只改动 `review/issue-7207/` 的提交：

- fix 分支的最新提交是 review 分支的祖先。
- 两个分支之间有差异的文件都在 `review/issue-7207/` 下。
- fix 分支上没有任何 `review/issue-*/` 文件。

**现状不满足。** 现有 review 分支（`7fa7a70`）是基线 `d8293547c` 加复现程序，不含修复，而且复现程序放在 `rust/lance/src/io/commit/` 里。需要重建。

**步骤：**

1. 从旧分支 `7fa7a70` 取出 `rust/lance/src/io/commit/repro_7207.rs` 和 `review/7207-results.md`，存到仓库外的临时目录。
2. 用 fix 分支的最新提交重建本地 review 分支：`git switch -C review/7207-failed-commit-index-cleanup fix/7207-failed-commit-index-cleanup`。
3. 在 `review/issue-7207/` 下建立这个结构，分成若干只动这个目录的提交：

   | 路径 | 内容 |
   | --- | --- |
   | `README.md` | 入口。分支角色与提交、上游基线、设计与范围、如何复现、按提交列出的结果、变异检查表、已知缺口、兄弟分支 |
   | `reports/` | 两份交付报告和 `HANDOFF_SUPPLEMENT.md` 的原文，以及本轮的收尾报告 |
   | `repro/repro_7207.rs` | 复现程序原文件 |
   | `repro/apply.sh` | 把复现程序装进任意一个检出：复制 `repro_7207.rs` 到 `rust/lance/src/io/commit/`，并在 `rust/lance/src/io/commit.rs` 的 `pub mod namespace_manifest;` 之后插入 `#[cfg(test)]` 和 `mod repro_7207;` 两行 |
   | `results/` | 每次运行的原始输出，文件名带被测提交的短 SHA；旧的 `7207-results.md` 原样放入并标注它测的是 `ab6f31589` |
4. 重新测量。分别在基线 `d8293547c` 和 fix 分支最新提交的一次性 worktree 里运行 `apply.sh`，然后：

   ```bash
   cargo test -p lance --lib repro_7207 -- --nocapture
   ```

   原始输出存进 `results/`。装了复现程序的 worktree 用完即删，不提交。
5. README 的要求：
   - 结果表每行写明被测提交及其与 fix 最新提交的关系。旧结果不得当作新代码的验证。
   - 变异检查表合并两份报告的 9 项：守卫、变异、失败的测试名。不用 `T`/`C` 编号，用测试函数名。
   - 已知缺口合并第一份报告第 8 节、增补报告第 5.2 节和第 5.4 节的缺口条目。
   - 兄弟分支列出 `fix/7207-reclaim-lost-commit-indices` 和 `-option-b` 两对，各写一句它发现了什么（自定义 remapper 的所有权、tagged fragment reuse 溢出目录的回收）。
   - 不写入任何 AI 会话或文档链接。交接单原文只在人提供了 Markdown 文件时才收入。
6. 分离检查。有 skill 时用它附录 A 的脚本；没有时运行下面三条，第 1、3 条输出必须为空，第 2 条退出码必须为 0：

   ```bash
   git ls-tree -r --name-only fix/7207-failed-commit-index-cleanup | grep '^review/issue-'
   git merge-base --is-ancestor fix/7207-failed-commit-index-cleanup review/7207-failed-commit-index-cleanup
   git diff --name-only fix/7207-failed-commit-index-cleanup review/7207-failed-commit-index-cleanup | grep -v '^review/issue-7207/'
   ```
7. 推送到 `easyrev/lance`：fix 分支普通 push。review 分支的历史被重建，**本单授权对 `review/7207-failed-commit-index-cleanup` 做一次 `git push --force-with-lease`**，仅此一个分支、仅此一次。旧 tip `7fa7a70` 的 SHA 写进 README。推送后用 `git ls-remote` 核对远端 SHA，并对远端引用再跑一次分离检查。

## 6. 停止条件与禁止动作

**遇到以下任一情况，停下并写明现状：**

- 任务 A、B 的“只动注释”检查输出不为空。
- 任务 C 的试合并有冲突。
- 试合并后有测试失败，而同一测试在纯 `upstream/main` 上通过。
- 复现程序在 fix 分支最新提交上报出的孤儿目录数不是 0，或在基线上不是 20。
- 分离检查不通过，且找不到只动 `review/issue-7207/` 就能修正的办法。
- `gh pr list --repo lance-format/lance --search 7207` 显示出现了覆盖 #7207 的新 PR。

**禁止的动作：**

- 不改任何非注释代码，不改测试断言和断言文案。
- 不 rebase、不 amend fix 分支上已有的提交；fix 分支不得 force push。
- 不向 upstream 推送，不开 PR，不在 GitHub 上评论。
- 不删除、不改名其它分支，包括两对旧的 `7207-reclaim-lost-commit-indices` 分支。
- 不从 review 分支向 fix 分支合并或 cherry-pick。
- 不补测试、不修已知缺口。

## 7. 交付物

1. fix 分支上的一个新提交，只含任务 A、B 的注释改动。
2. 重建后的 review 分支，满足第 5 节的不变量。
3. 收尾报告 `review/issue-7207/reports/CLOSING.md`，包含：
   - 任务 A 的编号 grep 输出，任务 B 的“只动注释”检查输出。
   - 试合并所用的 `upstream/main` SHA，是否有冲突，三条命令的结果和测试的通过、失败、忽略数。
   - 复现程序在基线和 fix 最新提交上的目录数与字节数，各自的提交 SHA。
   - 分离检查的结果（本地与远端各一次）。
   - 两个分支的本地 SHA 和远端 SHA。
   - 因为需要授权而没做的事。
