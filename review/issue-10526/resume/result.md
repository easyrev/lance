# 恢复执行结果

使用最初交接单的归档原文和本轮续跑指令。本机的 `/root/lance` 和 `/root/workspace` 未找到 `claude/10526-shared-buffer-handoff.md`，Git 记录中也没有该路径。阶段 0 只补写 0.4 和 0.5。复用原来的 7 份数据，新增 `binary-medium-default`。8 份 `.lance` 的哈希均已复核。

清理了列出的 tmpfs scratch、失败构建缓存和虚拟环境。归档日志转移到磁盘，保留 IPC 和数据文件。删除了本轮已归档哈希的旧 editable 引导扩展，并在用户明确授权后删除磁盘上的两个旧 target 和 sccache。授权清理后，`/` 和 `/dev/shm` 分别可用 71 GiB 和 77 GiB（`df -h`）。阶段 2 的 9 类 base/final 输出预估合计 12,172,885,724 字节（11.34 GiB），未实际写出。

| 构建 | 提交 | 导入扩展 SHA256 | 执行 |
|---|---|---|---|
| main | `cb8c25692e0d35d682be5459644a698f8d49655a` | `0e9064e38b9bc0caf08ad87111c69bbda4fd9fd752a37ac26d2061054ade9932` | 复用已有扩展，哈希与原记录一致 |
| pure-B | `16e3c99b1faa6014c17e33331f35cce726302243` | `798c26dc4ba394537e76e3b320050f7a2d7a463a7dc53651c6eec2d1806ad2fe` | 一次 `make build`，退出码 0 |
| pure-B-var | `6f16adfc7b2f6f2027926f2014fbcfebc7febb8c` | `ea1da9a40493c1bdf9d890fbacaab83ba34cb0aa3318e5b6e3ee4267cbe70a8e` | 一次 `make build`，退出码 0 |

候选串行使用 `release-with-debug` 编译，target、临时目录、uv 缓存和虚拟环境在磁盘。各自用 `uv sync --no-install-project` 准备依赖。每次安装后回收该构建的 target 并复核已安装扩展。测量使用 `LANCE_CPU_THREADS=64`。pure-B 的逐行校验在 pure-B-var 构建期间完成。全部 24 个精确性记录完成后才计时，各数据集的全量 scan 和随机排列 take 行数一致。

阶段 1 结束时有 24 个计时进程。`utf8-1page` 的 scan 完成三构建各 3 个进程，RSS 中位数 base→pure-B 增加 4.69%，base→pure-B-var 增加 3.52%，区间均相交。按规则各加至 5 个进程，两项增幅分别为 2.61% 和 1.42%，区间仍相交。`take(128)` 完成三构建各 3 个进程，每个进程 20 次调用，128 个排序行号经核对一致。

`take(128)` 首次调用后的峰值 RSS，base、pure-B、pure-B-var 的中位数分别为 202.66、210.40、211.34 MiB。相对 base，两候选分别增加 3.82% 和 4.28%，各自与 base 的区间均不重叠。pure-B-var 相对 pure-B 的进程峰值 RSS 增加 0.76%，区间不重叠。阶段 1 按 pure-B 回归条件结束，退出码 3。

`utf8-1page take(1024)`、其余数据集的计时、候选二选一、阶段 2 和选定提交的代码检查均未运行。保留之前的 Rust 编码测试日志，无新增代码提交。无推送，原 `perf/10526-wide-value-page-split` 仍指向 `d0020f429`。归档提交仅跳过 `ruff-format` 以保留已执行脚本的原始字节及 SHA256，其他 pre-commit 钩子照常执行。
