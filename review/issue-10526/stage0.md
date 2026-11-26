# 阶段 0

- 文件级交集只有 `rust/lance-encoding/src/compression.rs`。写端改动在 `try_variable_width_per_value`，B 新增方法在 `VariablePerValueDecompressor`。两个应用均无冲突。
- `16e3c99b1` 直接应用 `154270cf1..1d24f80fd`。`CompressedBufferEncoder::decompress` 函数体与 `cb8c25692` 相同，保留 B 对 `per_value_decompress` 的修改。`decompressed_size` 在 main 上已经存在。未引入 A 的容量预分配或测试，无其他补全。`cargo test -q -p lance-encoding --profile release-with-debug` 退出码 0，2614 个单元测试通过，3 个忽略，8 个文档测试通过，1 个忽略。
- `ed0a18841` 为 `d0020f429` 上应用 `16e3c99b1` 的结果。首次尝试误选了已在实验分支上的 `d0020f429`，空 cherry-pick 随即跳过，无额外提交。
- main 的 default 可产生无压缩 FullZip。`compression.rs:1108–1170` 按每页最大值和数据字节数选压缩器。`LargeBinary` 在最大值不超过 32 KiB 时可选 `VariableEncoder`，无需 compression metadata。超过 32 KiB 且满足最小数据字节数时用默认 Zstd（`encodings/physical/block.rs:710–722`），`block.rs:341–348` 无压缩率判断。默认配置高熵 12,000 行实测 110 页，全部为 Zstd FullZip。`compression.rs:1658–1694` 解析页编码，`fullzip_decode.rs:262` 按页创建解压器，同列可出现不同压缩器。选择实现 `pure-B-var` 供比较。
- `encodings/logical/primitive/structural_encoder.rs:394–428` 按页最大值选布局。默认稠密 `LargeBinary` 探针分别测得 255 B 为 MiniBlock，256 B、8 KiB、32 KiB、32 KiB + 1 B 为 FullZip。后三档中，8 KiB 和 32 KiB 页无压缩，32 KiB + 1 B 页为 Zstd。`binary-zstd-medium` 可用 8–32 KiB，并显式设置 `lance-encoding:compression=zstd`。
