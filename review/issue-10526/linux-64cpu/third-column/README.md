# 读端第三列

测量比较 `cb8c25692` 写出的文件（base 读），以及 `d0020f429` 写出的同一份文件（final 与 final+pure-B 读）。九类数据的 final 页编码中，无压缩可变长 FullZip 页数为 0。按交接单选择现有实验提交 `ed0a18841f39f845a8e963fd80cfb4d7689d5d43`，未叠加 pure-B-var。

四类 final 数据全部由 Zstd 可变长 FullZip 页组成，分别为 wide-unique、wide-unique-8k、wide-template、wide-mixed。wide-low-card 和 wide-repeated 为字典 MiniBlock，wide-clustered 包含 90 个常量页和 45 个字典 MiniBlock 页，wide-constant 为常量页，narrow 为 MiniBlock。逐页原始编码、文件哈希和布局汇总见 [数据文件](datasets.md)。

- 全量 scan 和单次 take(128) 使用原 [bench.py](../bench.py) 的读测入口。wide-unique 额外运行各 20 次的 take(128) 和 take(1024)。三列均来自本轮。各用例 3 个独立进程，区间相交且中位数增加超过 3% 时增至 5 个，保留两组结果。见 [三列完整表](summary.md)和 [回归](regressions.md)。
- 使用原判断标准的每组 3 进程中位数判断 `base → final` 和 `base → final+pure-B` 各自是否超过 **+10%**。见 [原先超过门槛的五项](five-rss-thresholds.md)。
- final+pure-B 对九类数据各做一次精确性校验，包括全量 scan 和全量随机排列 take。见 [审计日志](raw/phase2-audit.log)。
- 独立编译 target、临时目录和 Python 环境位于磁盘。使用 `release-with-debug` 和 `LANCE_CPU_THREADS=64`。base 与 final 的现有扩展先复核原 SHA256，实验扩展通过一次 `make build` 生成。见 [原始证据](raw/)及[脚本](scripts/)。
- base 和 final 的落盘文件估算共 11.34 GiB。每阶段的空间检查有留档。见 [逐项估算](space-estimate.md)和 [空间记录](raw/phase2-space.log)。

`pr-draft.md` 未在本轮编辑。归档提交仅跳过 `ruff-format`，保存执行脚本的字节。

`narrow` 首轮执行了全部 scan 和 take 等值断言，随后原校验脚本在生成摘要时对 Int64 调用 `binary_length` 并退出。保留了首轮日志。续跑仅令窄列的两个长度统计字段为 null，保留全部比较逻辑，并统一续跑退出码文件名后重新排队检查。仅 `narrow` 重新验证及完成计时。见 [原错误](raw/phase2-initial.log)和 [校验脚本差异](raw/phase2-narrow-verifier.patch)。

计时审计共 20 个用例、228 个独立计时进程、9 个精确性记录。按三进程原口径，final+pure-B 的原五项对照中，1 项低于 +10%，4 项高于 +10%。final+pure-B 的扩展 SHA256 为 `361d226a32d247ec6e957582670e18580f97bc5a84b93197c6be66356469364b`。
