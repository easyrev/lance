# 数据集与精确性门禁

八个数据集均由 base 写出，使用格式 `2.2`、seed 10526。流式写入以约 32 MB 分批。逐页编码原文、输入及文件哈希在 [raw/data](raw/data)。

| 数据集 | 内容 | 行数 | 写入 | 批数 | 压缩设置 | 页数 | 编码 | 文件字节数 | SHA256 |
|---|---|---|---|---|---|---|---|---|---|
| utf8-1page | 180,000 字节 LargeUtf8，4096 词表 | 25000 | RecordBatch | 1 | 默认压缩 | 1 | FullZip/Zstd × 1 | 1534797507 | `f01da6561d9fbad5f249d832bb8b85484628c69b13a6030742738e755edf26a9` |
| utf8-zstd-25k | 180,000 字节 LargeUtf8，4096 词表 | 25000 | RecordBatchReader | 142 | 默认压缩 | 142 | FullZip/Zstd × 142 | 1534824400 | `941cccd95d60bfa1ab1e4fefc3838ae2bbb7817e1ffa444b729f9e1936616dad` |
| utf8-zstd-8k | 180,000 字节 LargeUtf8，4096 词表 | 8000 | RecordBatchReader | 46 | 默认压缩 | 46 | FullZip/Zstd × 46 | 491135838 | `d955f401ac1669dd2bfd9e78d63a5718790edaa903ae130b06f64b2184ca8204` |
| binary-zstd-varlen | 64–512 KiB LargeBinary，4096 词表，1% null、1% 空值 | 12000 | RecordBatchReader | 110 | 默认压缩 | 110 | FullZip/Zstd × 110 | 1074702120 | `e4d9a94a00efd990d8f1cc5767edeb93c818abb74333a50ae8b653461754fbd1` |
| binary-random-varlen | 64–512 KiB LargeBinary，高熵随机字节，1% null、1% 空值 | 12000 | RecordBatchReader | 110 | 默认压缩 | 110 | FullZip/Zstd × 110 | 3479875086 | `e6de05d2b3c40eece060faf9b873ebb574fbddad07c3e0864436fed63b8f55c7` |
| binary-zstd-medium | 8–32 KiB LargeBinary，4096 词表，1% null、1% 空值 | 99650 | RecordBatchReader | 63 | compression=zstd | 63 | FullZip/Zstd × 63 | 1010593900 | `86f710c4f26f4e0a1aa90b7dffe84d61f0bb3aadf9118971c56ef6b9438d1717` |
| binary-medium-default | 8–32 KiB LargeBinary，4096 词表，1% null、1% 空值 | 99650 | RecordBatchReader | 63 | 默认压缩 | 63 | FullZip/Variable × 63 | 2003975714 | `46b48a080d5e5c42dc3dec499ec40fae5e8bb2e1c277e4c5b2cfcacd472c3a44` |
| mixed | LargeBinary，前半 8–16 KiB、后半 64–128 KiB，1% null、1% 空值 | 16000 | RecordBatchReader | 28 | 默认压缩 | 28 | FullZip/Zstd × 25、FullZip/Variable × 3 | 386927608 | `16cac18315559f9ff261ec085deb5e764607a2815cae4ca4be0ad5de6816263d` |

## 精确性门禁

两个构建分别执行一次全扫描和一次全量随机排列 take。使用 Arrow 逐位置比较行值和 null。take 返回后分块比对以控制额外内存。

| 数据集 | 构建 | 扫描行数 | 随机排列 take 行数 | 结果 |
|---|---|---|---|---|
| utf8-1page | base | 25000 | 25000 | 逐行一致 |
| utf8-1page | head | 25000 | 25000 | 逐行一致 |
| utf8-zstd-25k | base | 25000 | 25000 | 逐行一致 |
| utf8-zstd-25k | head | 25000 | 25000 | 逐行一致 |
| utf8-zstd-8k | base | 8000 | 8000 | 逐行一致 |
| utf8-zstd-8k | head | 8000 | 8000 | 逐行一致 |
| binary-zstd-varlen | base | 12000 | 12000 | 逐行一致 |
| binary-zstd-varlen | head | 12000 | 12000 | 逐行一致 |
| binary-random-varlen | base | 12000 | 12000 | 逐行一致 |
| binary-random-varlen | head | 12000 | 12000 | 逐行一致 |
| binary-zstd-medium | base | 99650 | 99650 | 逐行一致 |
| binary-zstd-medium | head | 99650 | 99650 | 逐行一致 |
| binary-medium-default | base | 99650 | 99650 | 逐行一致 |
| binary-medium-default | head | 99650 | 99650 | 逐行一致 |
| mixed | base | 16000 | 16000 | 逐行一致 |
| mixed | head | 16000 | 16000 | 逐行一致 |
