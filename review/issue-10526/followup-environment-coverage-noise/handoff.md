上一轮的数据保留。这一轮只做三项检查，不改任何代码，不动任何纯分支。

## 1. 环境对照

- 对 base、pure-B、pure-B-var、final、final+B 五个虚拟环境分别做 `pip freeze`，列出差异。
- 每个环境跑 5 个进程，记录只 `import pyarrow` 之后的 RSS，以及只 `import numpy` 之后的 RSS（两者都在 `import lance` 之前）。
- 新建一个和 pure-B 完全相同方式创建的虚拟环境，只把扩展换成 base（`cb8c25692`）的构建。用它重做 `utf8-1page` 的归因测量（import 后、open 后、首次 take(128) 后），每个构建 5 个进程，交替运行。
- 结论写明：7.4 MiB 增量来自环境，还是来自扩展本身。

## 2. 快路径覆盖

用上一轮的 uprobe 方法，统计 `decode_variable_into` 和 `concat_decoded_arrays` 的调用次数：
- pure-B 和 pure-B-var 各对 `binary-medium-default`、`mixed`、`binary-zstd-medium` 做一次 take(128) 和一次 scan；
- final+B 对 wide-repeated、wide-clustered 各做一次 take 和一次 scan。

## 3. scan 峰值 RSS 的噪声

- 在 `binary-zstd-medium` 上，pure-B 和 pure-B-var 各跑 7 个进程的 scan，交替运行。
- 再拿 pure-B 自己连续跑两组、每组 7 个进程，做一次 A/A 对照，报告同一个构建两组之间中位数的差。

把三项结果写进 `review/fullzip-variable-shared-buffers`，推送。纯分支不推送，不开 PR。