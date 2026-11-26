# 环境、快路径覆盖和扫描 RSS 复核

本轮使用上一轮的五个扩展，各自的 SHA256 与归档一致。上一轮证据保持独立。本轮六份读测文件按上一轮命令在新 tmpfs 目录重建，五份 IPC 输入及六份 Lance 数据文件的 SHA256 与上一轮一致。无扩展重编译。测量使用 `LANCE_CPU_THREADS=64`。样本和命令见 [原始归档](evidence.tar.gz)，完整数据表见 [结果](report.md)。

## 环境对照

五套原环境均为 Python 3.12.16，`pip freeze --all` 有 72 个相同的非 editable 条目。各环境的 editable pylance 来源及提交单独列出。每套环境的每种单独 import 各跑 5 个新进程。pure-B 相对 base 只导入 PyArrow 和 NumPy 后的 RSS 中位数分别高 4.31 和 5.18 MiB，采样时尚未导入 Lance。

用 pure-B 的 `uv sync --frozen --python 3.12 --no-install-project` 方式另建一个环境，在同一 editable Python 包路径下交替加载 base 和 pure-B 的原始扩展。两个提交之间的 Python 源码相同。新环境的非 editable 包条目也全部一致。每个构建跑 5 个新进程，并交替运行。

上一轮约 7.4 MiB 的增量归因于环境。相同 base 扩展在新环境中的 import RSS 中位数高 8.12 MiB。控制环境后，pure-B 相对 base 在 import、open、首次 take(128) 的差值分别是 -0.51、-0.51、+1.44 MiB，三个检查点的区间均重叠。这一对照未进一步定位环境内造成差额的具体组件。

## 快路径覆盖

探针为 `VariableFullZipDecodeTask::decode_variable_into` 和 `concat_decoded_arrays` 的方法入口。沿用上一轮的 uprobe 文件偏移解析。每项一次 take(128) 和一次全表 scan；用完移除本轮注册的全部探针。页任务调用次数与拼接调用次数各自计数。

pure-B 对 `binary-medium-default` 的两项快路径计数均为 0。pure-B-var 分别记录 56 和 122 次。mixed 的 take 从 pure-B 的 0 次快路径和 1 次拼接，变为 pure-B-var 的 26 次快路径和 0 次拼接。两者对 Zstd 中等值的探针计数一致。final+B 对 wide-repeated 和 wide-clustered 的 take 和 scan 快路径计数均为 0。

## Scan 峰值 RSS

`binary-zstd-medium` 的交替 A/B 各 7 进程，pure-B-var 相对 pure-B 的中位数增加 46.46 MiB（2.07%），区间重叠。pure-B 自身连续两组各 7 进程，第二组相对第一组的中位数下降 81.09 MiB（3.40%），区间重叠。本轮 A/B 没有复现上一轮 +15.75% 的分离区间，中位数差小于这次 A/A 对照中的绝对差。

## 归档

`evidence.tar.gz` 保存完整 freeze 输出、原始样本、探针命令和执行脚本。原始文本以无时间戳 gzip 保存，避免拼写钩子改写 ELF 表头和 Rust 符号。上一轮的 [阶段 1](../complete/phase1.md) 与 [归因](../complete/attribution.md) 保留原样。
