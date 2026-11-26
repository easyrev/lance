# 交接单：读端共享缓冲解码的独立验证，以及 #10526 的第三列

## 背景

#10526（写端切页，`perf/10526-wide-value-page-split` = `d0020f429`）把一个超大页切成多页之后，多页读取会碰到 main 上本来就有的 `concat_decoded_arrays` 双倍分配。上一轮的实验 B（`1d24f80fd`）让多页的可变长 FullZip 解码直接写进共享缓冲，在 wide-unique 一类数据上基本消除了读端开销。

现在要拆成两个 PR：

- **PR 1**：只有 B，基于 upstream main，不依赖 #10526。
- **PR 2**：#10526 本身，不改代码，补一列"加上 B 之后"的读端数据。

这一轮要回答三个问题：

1. B 在 main 上单独成立吗？它对 main 写出的多页文件有收益吗？对单页文件、不走快路径的文件有没有回归？
2. 要不要把无压缩 `VariableDecoder` 也接进快路径（下面叫 `pure-B-var`）？
3. 加上 B 之后，#10526 原来的 5 项读端 RSS 超标还剩几项？

## 提交

| 名称 | 提交 |
| --- | --- |
| base（upstream） | `cb8c25692` |
| final（#10526） | `d0020f429` |
| 实验 A | `154270cf1`（这一轮不用） |
| 实验 B | `1d24f80fd`（父提交是 A） |

## 硬性约束

- 不改 `perf/10526-wide-value-page-split`，它必须一直指向 `d0020f429`。
- 不开 PR，不写 PR 正文。结论部分只写数据和事实。
- 所有构建都用 `release-with-debug` profile，测量时 `LANCE_CPU_THREADS=64`。每个构建用独立的 target 目录和虚拟环境，并记录导入的 Python 扩展的 sha256。
- 数据和输出放在 `/dev/shm/lance-10526/shared-buffer/` 下。每个阶段开始前检查 `df -h /` 和 `df -h /dev/shm`，任何一个低于 10 GiB 就停下来汇报。
- 复用 `review/10526-wide-value-page-split` 分支上 `review/issue-10526/linux-64cpu/decode-followup/` 里的工具：`common.sh`、`build-experiment.sh`、`take.py`、`verify.py`、`inspect_data.py`。`take.py` 里写死了 `choice(25000, ...)`，要改成按数据集的实际行数取。除了这个参数化，不要改动计时边界和 RSS 的采集方式。
- 不要跑 11 月 18 日那套多 writer 写入矩阵，B 不改写入路径。
- 遇到不达标的结果，如实记录。不要为了过线而调代码、换统计方式或者合并几轮的数据。

## 阶段 0：准备，以及两个前置判断

阶段 0 的结论写进结果记录，然后再进入阶段 1。

### 0.1 diff 交集

列出 `git diff --stat cb8c25692 d0020f429` 涉及的文件，和 B 改动的文件（`compression.rs`、`decoder.rs`、`encodings/physical/block.rs`、`fullzip_decode.rs`、`field.rs`）比对，记录有没有交集。如果有交集，并且下面 0.2 的冲突不是机械性的，就停下来汇报。

### 0.2 构造 pure-B

- 从 `cb8c25692` 开始，只应用 B 相对 A 的改动，也就是 `154270cf1..1d24f80fd`。
- `block.rs` 预计会有冲突。解决方法：`CompressedBufferEncoder::decompress` 保持 main 的原样，B 新增的 trait 方法和实现保留。
- 检查 B 的代码有没有用到 A 引入的东西。如果用到了，在 pure-B 的提交里做最小的补全，并记录补了什么。
- pure-B 只能是一个提交，提交信息沿用 `perf(encoding): decode variable full-zip pages into shared buffers`。
- 跑 `cargo test -p lance-encoding --profile release-with-debug`，B 原有的单元测试必须全部通过。

### 0.3 构造 final+B

把 0.2 的 pure-B 提交 cherry-pick 到 `d0020f429` 上，放在单独的实验分支上。阶段 2 要用这个构建。如果后来选用了 `pure-B-var`，再把它也叠上去。

### 0.4 要不要做 pure-B-var

读 `cb8c25692` 中可变长 FullZip 选择压缩器的代码，回答下面两个问题，并附上代码位置：

1. 默认配置下（字段没有设置 compression metadata），可变长 FullZip 页会不会不压缩写出，也就是读的时候用 `VariableDecoder`？例如遇到不可压缩的数据时，会不会自动放弃压缩？
2. 同一个文件的同一列里，不同页能不能用不同的解压器？

然后用实测核对代码结论：用 main 的默认配置写一份高熵随机 `LargeBinary`（就是阶段 1 的 `binary-random-varlen`），用 `inspect_data.py` 看每页的编码。

判断规则：

- 两个问题有任何一个是"会"，就做 `pure-B-var`，实现方式见下一节。
- 两个都是"不会"（只有手动设置 `compression: none` 才会出现无压缩页），就不做 `pure-B-var`，也不构建，只把结论写进记录。

### 0.5 中等大小的值会不会走 FullZip

读代码，并用 main 实测：可变长值平均多大时，main 会选 FullZip 而不是 MiniBlock？阶段 1 的 `binary-zstd-medium` 要按这个结论定值的范围。

## pure-B-var（只在 0.4 判定要做时才做）

在 pure-B 上新增一个独立的提交，给 `rust/lance-encoding/src/encodings/physical/binary.rs` 里的 `VariableDecoder` 实现 B 新增的那两个方法（统计追加字节数、直接写进外部缓冲）：

- 支持 32 位和 64 位 offset。
- 校验 offset buffer 的长度，并校验每个值都满足 `start <= end <= data.len()`。要支持起始 offset 不为 0 的切片 block。
- 校验失败时，返回值要能让调用方回退到现有路径，或者走现有的报错路径。不能 panic。
- 写入外部 offset 时检查 u32/u64 溢出。
- 不用 `unsafe`。

需要补的测试：

- 同一批里同时有 Zstd 页和无压缩页时，走快路径，并且结果完全一致。要覆盖 null、空值、多字节 UTF-8、`Binary` 和 `LargeBinary`。
- 遇到不支持的解码器（比如字典页）时，仍然回退到 `concat_decoded_arrays`。
- offset 畸形或者越界时，回退或者报错，不会 panic。

## 阶段 1：PR 1 的证据（main 对比 pure-B）

### 构建

main（`cb8c25692`）和 pure-B；如果做了 `pure-B-var`，再加上它。

### 数据集

全部由未修改的 main 写出，用 `data_storage_version="2.2"`，放在 tmpfs 上。所有构建读同一批文件，记录每个文件的哈希。

每个数据集写完以后，先用 `inspect_data.py` 记录页数和每页编码，再开始测量。多页数据集用多个 batch 流式写出（`pa.RecordBatchReader`），每个 batch 的逻辑载荷约 32 MB。如果多 batch 写入没有产生多页，就停下来汇报，不要强行构造。记录实际的写入方式。

| 名称 | 内容 | 规模 | 作用 |
| --- | --- | --- | --- |
| `utf8-1page` | 复用 `/dev/shm/lance-10526/ipc/wide-unique.arrow`，一个 batch 写出 | 25,000 行，必须是 1 页 | 单页对照组，B 不应该有任何影响 |
| `utf8-zstd-25k` | 同上，多 batch 写出 | 25,000 行，多页 | 和 #10526 的数据对齐 |
| `utf8-zstd-8k` | `wide-unique-8k.arrow`，多 batch 写出 | 8,000 行，多页 | 和 #10526 的 8k RSS 判断标准对齐 |
| `binary-zstd-varlen` | `LargeBinary`，长度在 64–512 KB 之间，固定 seed 随机取；内容用和 `bench.py` 一样的 4,096 词表拼接（约 3 倍可压缩）；1% null，1% 空值 | 12,000 行 | 变长、可压缩的大值 |
| `binary-random-varlen` | 长度分布同上，内容是高熵随机字节，默认配置写出；1% null，1% 空值 | 12,000 行 | 不可压缩的数据；记录默认配置下实际用了什么编码 |
| `binary-zstd-medium` | `LargeBinary`，按 0.5 的结论取一个走 FullZip 的中等值范围（目标是 8–32 KB，必要时把下限提高到 FullZip 的阈值）；可压缩；1% null，1% 空值 | 总逻辑大小约 2 GB | 每页有上千个值时，逐值循环的开销有多大 |

如果 `/dev/shm/lance-10526/ipc/` 下的输入已经不在了，用 `review/issue-10526/linux-64cpu/bench.py` 的生成器重新生成，并核对哈希和上一轮是否一致。

如果做了 `pure-B-var`，并且 main 能自然写出同一列里压缩页和无压缩页混在一起的文件，就再加一个 `mixed` 数据集。不能自然写出的话，只靠单元测试覆盖，不要硬造。

### 测量

- 每个构建、每个数据集、每项测量都跑 3 个独立的新进程，各个构建交替运行。报告中位数和 [min–max]。
- **精确性（前置门禁）**：每个构建对每个数据集跑 `verify.py`，也就是全量 scan 加上全量随机排列的 take，逐行比对。必须 100% 一致，才能进入计时。
- **全表扫描**：所有数据集，计时包含 dataset open，`batch_size=1024`。记录耗时和进程峰值 RSS。
- **重复 take**：用同一个 dataset 句柄连续 take 20 次，行号排好序，seed 固定为 10526，所有构建用同一组行号。记录第 1 次、第 2 次、第 6–20 次的中位数，以及第 1 次之后和整个进程的峰值 RSS。
  - take(128) 和 take(1024)：`utf8-1page`、`utf8-zstd-25k`、`binary-zstd-varlen`、`binary-random-varlen`、`binary-zstd-medium`
  - take(128)：`utf8-zstd-8k`

## 阶段 2：#10526 的第三列（base / final / final+B）

### 构建

base、final，以及 0.3 的 final+B。如果选用了 `pure-B-var`，final+B 也要包含它。

### 数据

#10526 原来的 9 类数据：wide-unique、wide-unique-8k、wide-low-card、wide-repeated、wide-template、wide-clustered、wide-mixed、wide-constant、narrow。复用 `/dev/shm/lance-10526/ipc/` 下的输入。base 读 base 写出的文件；final 和 final+B 读同一份 final 写出的文件。记录页数和每页编码。

对每类数据，根据页编码说明：在 final 写出的文件里，是不是所有页都是可变长 FullZip（也就是 B 的快路径覆盖得到），还是含有字典页、常量页这类会回退的页。

### 测量

- 精确性：final+B 对 9 类数据各跑一次 `verify.py`。
- 9 类数据都测全表扫描和一次 take(128)，口径和 `linux-64cpu/summary.md` 一样：每个进程只做一次读取，3 个进程。
- wide-unique 再做一组重复 take，口径和 `decode-followup.md` 一样：take(128) 和 take(1024)，各 20 次。

### 和原来的判断标准对照

按 `linux-64cpu/criteria.md` 里的标准（读端峰值 RSS 不能比 base 高 10% 以上），逐项列出原来超标的 5 项（wide-unique-8k scan、wide-repeated scan、wide-repeated take、wide-clustered scan、wide-clustered take）在 base → final 和 base → final+B 下的变化，并标明每一项是否达标。

## 怎么判断回归和取舍

- **回归**：中位数变差，并且两边的 min–max 区间不重叠。如果区间重叠，但中位数变差超过 3%，就把那一项加跑到 5 个进程，两组结果都报告。
- **pure-B 要过的条件**：在 `utf8-1page`，以及其他所有不走快路径的数据集上没有回归；在多页可变长 FullZip 数据集上有收益。只要有回归，就停下来汇报，不要调代码。
- **pure-B 和 pure-B-var 二选一**：只有当 `pure-B-var` 在无压缩页（或混合页）上有收益，并且在其他数据集上相对 pure-B 没有回归时，才选 `pure-B-var`。否则选 pure-B，`pure-B-var` 只把对比结果留在记录里。

## 代码检查（对最终选定的提交）

- `cargo fmt --all -- --check`
- `cargo test -p lance-encoding -p lance-file --profile release-with-debug`
- `cargo clippy -p lance-encoding --tests --profile release-with-debug -- -D warnings`
- `cargo clippy --all --tests --benches -- -D warnings`：记录退出码和完整日志。如果有和这次改动无关的已有问题，在记录里标明它们已经存在，以及是在哪些文件里。

每项都保留日志。

## 发布（按 `$issue-branches`）

- **PR 1 的纯分支**：`perf/fullzip-variable-shared-buffers`，起点是 `cb8c25692`。只包含最终选定的提交：pure-B；如果选了 `pure-B-var`，再加上它那个独立的提交。不包含任何脚本或报告。
- **实验分支**：final+B 放在 `exp/10526-final-with-shared-buffers`。
- **PR 1 的 review 分支**：`review/fullzip-variable-shared-buffers`，内容包括：
  - 阶段 0 的结论，附代码位置
  - 构建表：提交 SHA 和扩展的 sha256
  - 数据集表：生成方式、页数、页编码、文件哈希
  - 阶段 1 的对比表：中位数、区间、变化百分比
  - 二选一的结论
  - 代码检查日志、脚本、原始数据、`SHA256SUMS`
- **阶段 2 的结果**：放进现有的 `review/10526-wide-value-page-split`，路径是 `review/issue-10526/linux-64cpu/third-column/`。内容是三列对比表、5 项超标的对照，以及原始数据。不要改 `pr-draft.md`。
- 发布前跑 `$issue-branches` 的分支隔离检查和引用检查，确认输出 `RESULT: separated` 和 `RESULT: no references`。
- 确认 `perf/10526-wide-value-page-split` 仍然指向 `d0020f429`。
- 清理 `/dev/shm` 下的数据和输出。释放实例之前，确认上面的内容都已经推送。

## 汇报

- 各个分支的链接和最终选定的 SHA
- 阶段 0 的四个结论（0.1、0.2 里补了什么、0.4、0.5）
- 阶段 1、阶段 2 的核心表格
- 所有回归和不达标项，如实列出
- 代码检查结果