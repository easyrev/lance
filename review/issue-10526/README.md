# FullZip 共享缓冲读端验证

选定提交 `16e3c99b1faa6014c17e33331f35cce726302243`（pure-B），基于 `cb8c25692`。实验时使用独立的磁盘 Cargo target、虚拟环境和临时目录，Python 扩展采用 `release-with-debug`，读测使用 `LANCE_CPU_THREADS=64`。

| 阶段 1 构建 | 提交 | 导入的扩展 SHA256 |
|---|---|---|
| main | `cb8c25692e0d35d682be5459644a698f8d49655a` | `0e9064e38b9bc0caf08ad87111c69bbda4fd9fd752a37ac26d2061054ade9932` |
| pure-B | `16e3c99b1faa6014c17e33331f35cce726302243` | `798c26dc4ba394537e76e3b320050f7a2d7a463a7dc53651c6eec2d1806ad2fe` |
| pure-B-var | `6f16adfc7b2f6f2027926f2014fbcfebc7febb8c` | `ea1da9a40493c1bdf9d890fbacaab83ba34cb0aa3318e5b6e3ee4267cbe70a8e` |

- 阶段 0 的改动交集、移植、页布局与压缩器选择见 [阶段 0](stage0.md)和 [代码位置补充](resume/stage0-supplement.md)。
- 8 个阶段 1 数据集均由 main 写出。同一数据集的三套读端使用相同文件。共 24 个精确性记录，所有 scan 和 take 行数一致。见 [数据集、页编码与文件哈希](resume/datasets.md)和 [计时审计](complete/raw/phase1-audit.log)。
- 单页归因每构建 5 个独立进程。perf 探针分别记录追加页任务及数组拼接。见 [单页 RSS、并列的二进制大小和 uprobe 次数](complete/attribution.md)。
- 阶段 1 共 23 个用例及 249 个计时进程。单页 scan 和 take(128) 完整保留上一轮收集的样本。其余用例在本轮完成，呈现各用例自己的 3 进程和必要时 5 进程结果。见 [阶段 1 全表](complete/phase1.md)、[各比较方向的回归](complete/phase1-regressions.md)和 [候选取舍](complete/selection.md)。
- 最终代码检查包含 fmt、联合测试和两项 Clippy。见 [各命令与退出码](complete/checks.md)。
- 阶段 2 的 base、final、final+pure-B 三级证据位于 `review/10526-wide-value-page-split` 的 `review/issue-10526/linux-64cpu/third-column/`。
- 原始 [交接单](complete/original-handoff.md)、[恢复指令](resume/handoff.md)及[本轮覆盖指令](handoff.md)均已归档。见 [原始数据](complete/raw/)和[脚本](complete/scripts/)。

## 运行记录

对照组的两个新增 RSS 记录点只用于单页归因。正式计时继续使用原始 `take.py` 和原有 RSS 记录点。`take-rss-stages.py.txt` 字节与执行脚本一致，复现时将文件名还原为 `take-rss-stages.py`。这是为了保存 import 之间的 RSS 采样位置。归档提交仅跳过 `ruff-format`，保留执行脚本的字节和哈希。纯分支没有新提交。

第一次符号探针注册用于验证 perf 能力，验证后移除。计数用 `perf probe -x` 加 ELF 文件偏移，测完后删除本轮探针。fork 发布范围为两个 review 分支及阶段 2 实验分支。

单页归因的原始记录以无时间戳 gzip 保存。拼写钩子把 readelf 表头缩写和 Rust 符号哈希识别为拼写错误。压缩后逐字节核对原输出，拼写钩子续跑时保持启用。见 [归因归档](complete/raw/attribution.tar.gz)。

## 后续复核

[环境、快路径覆盖和扫描 RSS](followup-environment-coverage-noise/README.md)包含交叉环境对照、16 个 probe 读测和 28 个 scan RSS 样本。交叉对照更新了上一轮的单页 RSS 归因，原始计时与探针数据均保留。

## PR 数字的匹配环境复测

[matched-env](matched-env/README.md)保留独立的正式组和同构建 A/A 组，并给出噪声门槛及每项判定。此前各轮的原始样本和汇总保留原样。
