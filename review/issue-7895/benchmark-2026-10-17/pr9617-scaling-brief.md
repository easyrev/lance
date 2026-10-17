# PR #9617 scaling benchmark — 执行说明

## 0. 背景

- 仓库：`lance-format/lance`。PR 分支：`easyrev/lance:feat/7895-rescannable-sources`（PR #9617，关联 issue #7895）。
- 问题：Python 把 `LanceDataset`、`pa.dataset.Dataset` 转成一次性的 `RecordBatchReader` 再交给 Rust。Rust 端在 `conflict_retries > 0` 时（默认值是 10），会通过 `spilling_table_provider` 把整个源缓冲下来，以便重试时重放：前 100 MB 放内存，超出部分写到 `tempfile::tempdir()` 下的临时文件。**无论最终是否发生冲突，这个缓冲都会建立**。
- PR 的做法：保留"源可以重新扫描"这一语义，让符合条件的源走可重复扫描的 `TableProvider`，重试时直接重扫，不建立缓冲。不符合条件的源（不透明的 Scanner、一次性 reader）保持原有行为。
- 已有结果：输入为 132 MiB 时，replay spill 从约 132 MiB 降到 0。无冲突时延迟降低约 5%。**真实发生重试时，PR 版本多用约 6.8% CPU、峰值 RSS 多约 39 MiB，原因未查明**。
- 本轮目的：
  1. 给出规模曲线，证明缓冲成本随源的字节数线性增长，而 PR 版本在各个规模下都没有这部分成本；
  2. 查明并解释上面那条重试开销的回退。

## 1. 要回答的问题与预先登记的假设

| # | 问题 | 预期 |
|---|---|---|
| H1 | upstream 的 spill 写盘字节是否约等于 max(0, 源大小 − 100 MiB)？ | 是 |
| H2 | 对符合条件的源，PR 版本的 spill 是否在所有规模下都为 0？ | 是 |
| H3 | 无冲突时，PR 的 CPU 和墙钟时间是否接近 `retries=0` 这个下限，而 upstream 与下限的差距是否随规模扩大？ | 是 |
| H4 | 有冲突时，PR 多出的 RSS 是常数，还是随源大小增长？ | 未知，**这是本轮最关键的问题** |
| H5 | 对照组（不透明 Scanner、RecordBatchReader）在两个版本上的行为和字节数是否完全一致？ | 是 |
| H6 | 临时目录容量小于源大小时，upstream 是否失败，PR 是否成功？ | 是，但需要实测 |

**判定规则**（开跑前就定下来，不能事后修改）：

- H2 或 H5 不成立：立即停止，报告原因。这说明资格判断或回退逻辑有问题，此时规模数据没有意义。
- H4 的结果是"随规模增长"：先完成第 5 节的根因分析，再跑剩余档位。
- 只要源大小 ≥ 1 GiB 的任一档出现 PR 无冲突中位延迟比 upstream 慢 5% 以上，标记出来并分析原因。
- **测量期间不修改 PR 代码**。如果分析后认为需要修改，单独提交 commit，向我说明理由，经我确认后重跑受影响的档位。

## 2. 开工前先核实（任何一项与描述不符，都先报告再继续）

1. Python 的 `merge_insert(...)` 默认 `conflict_retries` 是否为 10，以及默认路径是否会经过 `stream_source_to_provider`。
2. spill 文件是否确实写在 `TMPDIR` 指定的目录下（`tempfile::tempdir()` → `std::env::temp_dir()`）。H6 依赖这一点。
3. spill 是在执行路径分叉（`can_use_create_plan`）之前建立的，所以 legacy 索引路径和 DataFusion 路径都会受影响。请确认这一点，并确认 PR 版本在两条路径上都能避免 spill。
4. 冲突注入：沿用 PR 测试里 `_source_retry_commit_lock` 的写法，通过 commit hook 在第一次提交前插入一次竞争提交。要保证**恰好发生一次冲突、恰好重试一次**，并通过 merge stats 或日志确认重试次数。
5. 重试的退避（backoff）是随机的，查清它对墙钟时间的影响。如果能在不改 PR 逻辑的前提下关掉或固定它（例如通过参数），就照做并写明；否则在有冲突的场景下以 CPU 时间和字节数为主要指标，墙钟时间只作参考。

## 3. 构建

- 把 PR rebase 到最新 main，记录两边的 commit hash。rebase 后完整运行一遍 PR 改动涉及的 Python 和 Rust 测试。
- 两套构建都用相同的 profile（`release-with-debug`），分别装进两个独立的 venv：`venv-upstream` 和 `venv-pr`。
- 安装 `perf`、`heaptrack`（或 bytehound），供第 5 节使用。

## 4. 实验矩阵

**数据**（生成一次，两个版本共用）：

- 行结构：`id: int64`、`vec: fixed_size_list<float32, 768>`、`label: string`（约 32 B）、`ts: timestamp`。每行约 3.1 KB，模拟 embedding 回填场景。
- 目标表：固定 4M 行（约 12 GiB），Lance 格式，`id` 为 0..4M，**`id` 上不建索引**（走 DataFusion 路径，这是主场景）。打一个 base tag，每轮测量前恢复到这个 tag，测量结束后清理产生的新版本，避免磁盘被撑满。
- 源：4 档，每档同时生成 Lance 数据集和 Parquet 目录两种格式：

  | 档位 | 约行数 |
  |---|---|
  | 128 MiB | 43K |
  | 1 GiB | 350K |
  | 4 GiB | 1.4M |
  | 16 GiB（可选，最后跑） | 5.5M |

  源里 50% 的 key 在目标表中已存在（会被更新），另外 50% 是新 key（会被插入）。key 随机分布。
- 操作：`merge_insert("id").when_matched_update_all().when_not_matched_insert_all()`。

**分组**：

| 层 | 内容 | 重复次数 |
|---|---|---|
| A 主曲线 | 全部档位 × 源类型 {LanceDataset（固定版本）, Parquet 构成的 `pa.dataset`} × {upstream, PR} × {无冲突, 1 次冲突} | 小于等于 4 GiB 的档位跑 5 次，16 GiB 跑 3 次 |
| A0 下限 | 同样的源，`conflict_retries=0`，只跑无冲突，两个版本都跑 | 同上 |
| B 对照组 | 1 GiB 档 × {不透明 `pa.dataset.Scanner`, `RecordBatchReader`} × 两个版本 × 有无冲突 | 5 次 |
| P 路径确认 | 1 GiB 档，在目标表 `id` 上建 BTREE 索引并设置 `use_index(True)`（legacy 路径），只跑无冲突，两个版本 | 3 次 |
| D 受限临时盘 | 4 GiB 档，把 `TMPDIR` 指向一个 2 GiB 的 loop 设备挂载点（在 NVMe 上创建 ext4 镜像，不要用 tmpfs），两个版本，无冲突 | 各 1 次，记录成功/失败和报错信息 |
| C 远程源（可选，最后做） | 1 GiB 档，源放在同地域的对象存储（S3/OSS，用实例角色授权，不要用长期密钥）；条件不具备时用本机 RustFS 并通过 toxiproxy 注入约 20 ms 延迟。两个版本 × 有无冲突 | 3 次 |

默认测热缓存（每次测量前预读一遍源）。另外在 4 GiB 档加测一组冷缓存（`sync; echo 3 > /proc/sys/vm/drop_caches`），A 层、两个版本、有无冲突各 3 次。

**测量方式**：

- **每次测量都启动一个新的子进程**，用 `getrusage(RUSAGE_CHILDREN)` 或 `/usr/bin/time -v` 获取峰值 RSS 和 user/sys CPU 时间，避免进程内的缓存和内存分配器状态干扰结果。
- upstream 和 PR **交替运行**（ABAB 顺序），抵消机器状态随时间的漂移。
- 记录以下指标：
  - 墙钟时间
  - user/sys CPU 时间
  - 峰值 RSS
  - 进程总写盘字节（`/proc/<pid>/io` 的 `write_bytes`）
  - 数据集写入字节（Lance 的 io stats）
  - **spill 字节**：用上面两者之差估算，再用临时目录的峰值占用量交叉验证
  - 源读取字节
  - 实际重试次数
  - 是否建立了 replay buffer（看日志或 trace）
- 每次运行后校验结果正确：目标表行数为 4M + 新增行数，抽样核对若干条被更新的行。

## 5. 根因分析：重试时的 CPU 和 RSS 回退

在 1 GiB 档、LanceDataset 源、1 次冲突的条件下：

- 用 `perf record -g` 对比两个版本的 CPU 热点，重点看多出来的时间花在哪里（第二次扫描的解码？Python 回调？schema 校验？）。
- 用 heaptrack 对比两个版本的分配峰值，查清 PR 版本多出的内存来自哪里。
- 结论要说明：这部分开销是可重扫设计本身固有的代价（比如重扫需要重新解码数据，而 upstream 读的是已解码的缓冲），还是可以优化的实现细节。如果是后者，给出修改方案和预估收益，**不要直接动手改**。

## 6. 产出

全部放在 `~/bench-9617/results/` 下，**不要 push，也不要在 GitHub 上发任何评论**：

- `raw.jsonl`：每次测量一行，包含全部指标和配置。
- `env.md`：实例型号、CPU、内存、磁盘类型、内核版本、两边的 commit hash、构建 profile、PyArrow 版本。
- `summary.md`，包含以下内容：
  1. 第 2 节各项核实的结论；
  2. H1–H6 各自成立与否，附上数据；
  3. **一份可以直接贴进 PR 的英文 Performance 小节**，包括以下表格：
     - 无冲突：源大小、行数、spill（upstream → PR）、墙钟中位数和 p90、CPU 时间、峰值 RSS，与 A0 下限并列；
     - 1 次冲突：同样的列；
     - 受限临时盘：成功/失败；
     - 明确列出没有测量的内容；
  4. 第 5 节的根因分析结论；
  5. 你认为数据中不可信或存在疑问的地方。
- 测试框架脚本放在 `~/bench-9617/harness/` 下，写法尽量和 `python/python/ci_benchmarks`（`datagen/merge_insert.py` 恢复到 tag 的做法、`io_mem_benchmark` fixture）保持一致，以便将来移植进去。但这次**不要提交到 PR**。

## 7. 节奏

- 按以下顺序推进，每个阶段完成后给一个简短的进展汇报：第 2 节核实 → 构建 → 生成数据 → 128 MiB 和 1 GiB 冒烟测试 → A、A0、B、P 层 → 第 5 节 → D 层 → 4 GiB 冷缓存 → 16 GiB 档 → C 层。
- 磁盘使用率超过 80% 时先清理再继续。
- 任何判断不了的问题，写下来交给我决定，不要自己猜。
