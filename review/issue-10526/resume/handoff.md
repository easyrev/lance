继续执行 claude/10526-shared-buffer-handoff.md，从阶段 1 的扩展构建开始。阶段 0 不用重做，阶段 1 已经写好的 7 个数据集也保留。先处理下面几件事，再恢复计时。

## 1. 存储布局

- 运行 `df -h / /dev/shm` 和 `du -sh /dev/shm/* /dev/shm/lance-10526/*`，把结果写进记录。
- 删除 `/dev/shm` 下前几轮留下的 scratch：`take-investigation/`、`decode-followup/` 的 Lance 输出，以及其他不属于本轮的数据。保留 `/dev/shm/lance-10526/ipc/` 和本轮的 7 个数据集。删除前列出要删的路径和大小。
- `CARGO_TARGET_DIR`、`TMPDIR`、`UV_CACHE_DIR` 和各个虚拟环境全部放到磁盘上，不放 tmpfs。`/dev/shm` 只放 Lance 数据集和读测时的输出。
- 每个构建只编一次扩展，用 `build-experiment.sh` 的方式，不要再先跑 `make install` 再跑 `make build`。
- 构建一个接一个地串行跑，不要两个同时链接。
- 磁盘保护规则不变：`/` 或 `/dev/shm` 的可用空间低于 10 GiB 就停下来汇报。阶段 2 开始前，估算 9 类数据的 base 输出和 final 输出加起来要多少空间，写进记录。

## 2. 补充阶段 0 的两个结论（计时之前）

- **0.4**：写出"同一列 25 页 Zstd 加 3 页无压缩"的是什么数据、什么配置？是不是默认配置？main 在什么条件下给可变长 FullZip 页选择不压缩？附代码位置。
- **0.5**：为什么 `binary-zstd-medium` 要显式设置 Zstd？不设置的时候，main 对 8–32 KiB 的值默认用什么编码？附代码位置和 `inspect_data.py` 的实测结果。

## 3. 新增一个数据集

`binary-medium-default`：值的分布和内容与 `binary-zstd-medium` 完全相同，用 main 的默认配置写出，不设置任何压缩 metadata。记录页数和每页编码。它和 `binary-zstd-medium` 测量项目相同，也要过精确性门禁。PR 1 和 pure-B-var 二选一的时候，以这个数据集为主要依据。

## 4. 其他

- PR 1 的纯分支 `perf/fullzip-variable-shared-buffers` 上的提交不能跳过任何 pre-commit 钩子。只有 review 分支上的归档提交可以跳过 `ruff-format`，而且要在记录里说明原因。
- 交接单其余部分保持不变。