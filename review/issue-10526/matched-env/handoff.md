最后一轮：在匹配的环境下重测 PR 要用的数字。不改代码，不重新编译。

## 环境

用和上一轮交叉对照相同的方式，新建 4 个虚拟环境，分别安装已有的 base、pure-B（`16e3c99b1`）、final（`d0020f429`）、final+B（`ed0a18841`）的扩展。除了扩展本身，这 4 个环境必须完全一致。确认 `pip freeze` 中除扩展以外的部分完全相同，并记录每个环境 `import lance` 之后的 RSS（5 个进程）。

## PR 1：base 对比 pure-B

- 数据集：沿用阶段 1 的全部数据集，不包括 pure-B-var。
- scan 的耗时和峰值 RSS：每个构建 7 个进程。
- 重复 take（take(128) 和 take(1024)）：每个构建 5 个进程。
- 两个构建交替运行。

## PR 2：base、final、final+B

- 数据集：#10526 的 9 类数据。
- scan：每个构建 7 个进程。
- take(128)：每个构建 5 个进程。
- wide-unique 再做一组重复 take，take(128) 和 take(1024)，每个构建 5 个进程。

## 统计口径

- 报告中位数、[min–max] 和变化百分比。
- 每个测量项都做一次 A/A：同一个构建在同一个环境里再跑一组，给出同构建两组之间中位数的差，作为这一项的噪声参照。
- 只有中位数的差超过同一项 A/A 差的两倍，并且区间不重叠，才记为回归或者收益。其余的都记为"在噪声内"。

## 交付

- PR 1 的结果写进 `review/fullzip-variable-shared-buffers`，PR 2 的结果写进 `review/10526-wide-value-page-split` 的 `third-column/matched-env/`。推送这两个 review 分支。
- 纯分支不推送，不开 PR，不写 PR 正文。