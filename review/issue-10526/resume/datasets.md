| 数据集 | 写入 | 页数 | 页编码及数量 | 文件字节数 | `.lance` SHA256 |
|---|---|---:|---|---:|---|
| utf8-1page | 25,000 行，RecordBatch，1 batch，默认压缩配置 | 1 | FullZip/General/CompressionAlgorithmZstd × 1 | 1,534,797,507 | `f01da6561d9fbad5f249d832bb8b85484628c69b13a6030742738e755edf26a9` |
| utf8-zstd-25k | 25,000 行，RecordBatchReader，142 batch，默认压缩配置 | 142 | FullZip/General/CompressionAlgorithmZstd × 142 | 1,534,824,400 | `941cccd95d60bfa1ab1e4fefc3838ae2bbb7817e1ffa444b729f9e1936616dad` |
| utf8-zstd-8k | 8,000 行，RecordBatchReader，46 batch，默认压缩配置 | 46 | FullZip/General/CompressionAlgorithmZstd × 46 | 491,135,838 | `d955f401ac1669dd2bfd9e78d63a5718790edaa903ae130b06f64b2184ca8204` |
| binary-zstd-varlen | 12,000 行，RecordBatchReader，110 batch，默认压缩配置 | 110 | FullZip/General/CompressionAlgorithmZstd × 110 | 1,074,702,120 | `e4d9a94a00efd990d8f1cc5767edeb93c818abb74333a50ae8b653461754fbd1` |
| binary-random-varlen | 12,000 行，RecordBatchReader，110 batch，默认压缩配置 | 110 | FullZip/General/CompressionAlgorithmZstd × 110 | 3,479,875,086 | `e6de05d2b3c40eece060faf9b873ebb574fbddad07c3e0864436fed63b8f55c7` |
| binary-zstd-medium | 99,650 行，RecordBatchReader，63 batch，compression=zstd | 63 | FullZip/General/CompressionAlgorithmZstd × 63 | 1,010,593,900 | `86f710c4f26f4e0a1aa90b7dffe84d61f0bb3aadf9118971c56ef6b9438d1717` |
| binary-medium-default | 99,650 行，RecordBatchReader，63 batch，默认压缩配置 | 63 | FullZip/Variable × 63 | 2,003,975,714 | `46b48a080d5e5c42dc3dec499ec40fae5e8bb2e1c277e4c5b2cfcacd472c3a44` |
| mixed | 16,000 行，RecordBatchReader，28 batch，默认压缩配置 | 28 | FullZip/Variable × 3、FullZip/General/CompressionAlgorithmZstd × 25 | 386,927,608 | `16cac18315559f9ff261ec085deb5e764607a2815cae4ca4be0ad5de6816263d` |
