# 阶段 0 补充

## 0.4 同列不同压缩器

`mixed` 是一个 16,000 行、单列 nullable `LargeBinary` 数据集。生成器用 seed `10526` 和 `bench.py` 的 4,096 词表生成载荷，前 8,000 行的非空长度在 8–16 KiB，后 8,000 行在 64–128 KiB，全表有 1% null 和 1% 空值。main 用 `pa.RecordBatchReader`（每批逻辑载荷约 32 MB）、默认配置、`data_storage_version="2.2"` 写入。字段没有 compression metadata，也没有指定布局。`inspect_data.py` 记录同一文件、同一列的 28 页。逐页编码是 3 页无压缩 `FullZip/Variable` 和 25 页 `FullZip/General/Zstd`。

main 的 `rust/lance-encoding/src/compression.rs:1108–1170` 按页判断压缩器。若 metadata 为 `none`，直接用 `VariableEncoder`。默认 `Binary`/`LargeBinary` 的本页最大值超过 32 KiB 且载荷达到 `FSST_LEAST_INPUT_SIZE` 时，走 `CompressedBufferEncoder::default()`，启用了 Zstd 的构建默认选 Zstd（`rust/lance-encoding/src/encodings/physical/block.rs:710–722`）。否则，二进制类型在默认配置下不进入 FSST，进入 `VariableEncoder`。默认字符串也可能在同一分支根据页统计选 FSST。Zstd 写入过程没有压缩率回退（`block.rs:341–348`）。读端在 `rust/lance-encoding/src/encodings/logical/primitive/fullzip_decode.rs:248–263` 按该页编码创建解压器，无压缩 `Variable` 由 `compression.rs:1658–1686` 映射到 `VariableDecoder`。

## 0.5 8–32 KiB 不同配置

`rust/lance-encoding/src/encodings/logical/primitive/structural_encoder.rs:394–428` 按页最大值选布局，普通稠密布局的 256 字节分界与压缩器的 32 KiB 分界分开。`compression.rs:1122–1151` 对默认配置的 Zstd 门槛用严格的 `max_len > 32 * 1024`。`binary-zstd-medium` 设置 `lance-encoding:compression=zstd`，让这些页通过显式压缩请求进入 Zstd 路径。其目的在于测量中等值的 Zstd FullZip 解码。

`binary-medium-default` 与 `binary-zstd-medium` 使用同一个 `binary-zstd-medium.arrow`（99,650 行），相同的 `RecordBatchReader` 方式写入，默认数据集不设置 compression metadata。`inspect_data.py` 记录默认数据集 63 页、2,003,975,714 文件字节、SHA256 `46b48a080d5e5c42dc3dec499ec40fae5e8bb2e1c277e4c5b2cfcacd472c3a44`，逐页编码全部为无压缩 `FullZip/Variable`。显式 Zstd 数据集的 63 页全部为 `FullZip/General/Zstd`。main 对默认数据集验证全量 scan 和随机 take，分别核对 99,650 行，含 996 个 null 和 996 个空值。
