# #10526 读端冷热对比与 Follow-up 解码优化验证交接单

## 环境与硬性约束

- 机器与目录：沿用 `/root/lance/{base,final}` 两个现有 worktree（`base = cb8c25692`，`final = d0020f429`），编译统一使用 `release-with-debug` profile，独立 target 目录与虚拟环境。
- 磁盘守卫：每阶段开跑前检查 `df -h /` 与 `df -h /dev/shm`，任一可用空间低于 10 GiB 立即停止并汇报。所有数据与临时输出放 `/dev/shm/lance-10526/decode-followup/`，用完及时清理无用数据文件。
- **严禁改动 `perf/10526-wide-value-page-split`（`d0020f429`）**：纯分支 SHA 必须保持不变，不要往上面提交任何读取端实验代码。
- **不要开 PR**；完成后按 `$issue-branches` 规范发布分支与评审数据。

---

## 阶段一：补全 `#10526` 的上游 vs 最终版冷/热连续取行测量（不改代码）

目的：直接对比 `base (cb8c25692, 1 page)` 与 `final (d0020f429, 135 pages)` 在同一进程内连续 `take` 的冷启动与稳态耗时，并验证 `1,024 行`（184.32 MiB > glibc 32 MiB `M_MMAP_THRESHOLD` 上限）在热态下是否也会收敛。

1. 复用 `/dev/shm/lance-10526/take-investigation/data/{base-default,final-default}`（若已清理则按原脚本用 `wide-unique.arrow` 重建，确认 `base = 1 page`、`final = 135 pages`）。
2. 对 `base` 和 `final`，分别在 `count = 128` 和 `count = 1024` 下，执行**同一进程、单个 `lance.dataset()` 句柄连续 `take` 20 次**（使用 `take.py --take-only --repeat 20`，seed 10526，两个版本行号完全一致，`LANCE_CPU_THREADS=64`）。
3. 每个 `(version, count)` 组合跑 **3 个独立进程**（交替跑 `base` 和 `final`），保存每次迭代的原始 JSONL。
4. 汇总记录：
   - 第 1 次（冷）的中位数与 min–max；
   - 第 2 次的中位数；
   - 第 6–20 次（热稳态）的中位数与 min–max；
   - 对比 `base → final` 的绝对差值（ms）与百分比变化。

---

## 阶段二：独立试验分支验证两个读端小改动（不动 `#10526` 主分支）

基于 `d0020f429` 新建独立 worktree 与分支（例如 `/root/lance/exp-decode`，分支名按 `$issue-branches` 规范命名，如 `exp/10526-decode-page-bridging`），**读取阶段一和原 benchmark 生成的同一份 `final` 多页文件**（因为下面两步都是纯读端改动，盘上文件字节完全不变）。

### 实验 A：解压精确预分配（~10–15 行）

- 位置：`rust/lance-encoding/src/encodings/physical/block.rs`
- 改动：在 `impl VariablePerValueDecompressor for CompressedBufferEncoder::decompress` 中，把 `Vec::with_capacity(data_bytes.len() * 2)` 改为先调用同实现内已有的 `self.decompressed_size(data_bytes, &data.offsets, data.bits_per_offset)` 获取精确解压字节数，用 `Vec::new()` + `try_reserve_exact(exact_bytes)`（失败返回 `Error::invalid_input`，避免损坏文件的超长前缀导致 panic/abort；若 `decompressed_size` 返回 `None` 则回退原 `data_bytes.len().saturating_mul(2)`）。
- 校验：运行 `cargo test -p lance-encoding`，编译 `release-with-debug` Python 扩展（记录 sha256），确认精确 round-trip（`wide-unique`、`wide-unique-8k`、`wide-mixed`）。
- 测量（读取 `final` 写出的多页文件，每项 3 次独立进程取中位数，并保留全部原始 trial）：
  1. `wide-unique`（135 页）：`take(128)` 与 `take(1024)` 的连续 20 次（冷第 1 次 + 热稳态 + 峰值 RSS）；
  2. `wide-unique-8k`（44 页）：`scan`（`batch_size=1024`，耗时 + 峰值 RSS）与 `take(128)`（耗时 + 峰值 RSS）；
  3. `wide-unique`（135 页）：`scan`（`batch_size=1024`，耗时 + 峰值 RSS）。

### 实验 B：Opt-in 跨页直写解码（Page Bridging，~100 行，仅动 `VariableFullZipDecodeTask`）

在实验 A 的提交之上新增第二个提交（保留 A、B 两个清晰提交以便单独复现）：

- **不要改字典、常量、MiniBlock 或 FixedWidth 解码器**，采用与 `StructuralPageDecoder::decoded_bytes` 一致的 opt-in 默认方法模式：
  1. `rust/lance-encoding/src/decoder.rs`：在 `pub trait DecodePageTask` 增加默认方法（默认返回 `None` / `not_supported`），用于查询单个页任务是否支持精确可变长直写（返回 `num_values`、`decompressed_bytes`、`bits_per_offset`）以及把解码结果直接追加到外部 `(out_data: &mut Vec<u8>, out_offsets_u32_or_u64)` 并返回 `RepDefUnraveler`。
  2. `rust/lance-encoding/src/encodings/physical/block.rs`：为 `VariablePerValueDecompressor`（及 `CompressedBufferEncoder`）增加将值直接追加解压进外部 `&mut Vec<u8>` 与外部 offsets buffer 的默认/覆写方法（注意支持 `bits_per_offset == 32 | 64`、空值/null 零长度跳过，且 offsets 基于外部 `out_data.len()` 累加）。
  3. `rust/lance-encoding/src/encodings/logical/primitive/fullzip_decode.rs`：仅为 `VariableFullZipDecodeTask` 实现上述 opt-in 方法。
  4. `rust/lance-encoding/src/encodings/logical/primitive/field.rs`：在 `StructuralCompositeDecodeArrayTask::decode` 中，当满足以下全部条件时走直写快路径，否则原样回退现有 `decode + concat_decoded_arrays` 路径：
     - `self.tasks.len() > 1`；
     - `self.data_type` 为 `Utf8 | LargeUtf8 | Binary | LargeBinary`；
     - 所有子任务均返回 `Some(plan)` 且 `bits_per_offset` 与 `self.data_type` 一致（32 对应 `Utf8/Binary`，64 对应 `LargeUtf8/LargeBinary`）；
     - 若为 32 位偏移，`total_bytes <= i32::MAX as usize`。
     - 一次性 `try_reserve_exact(total_bytes)` 分配单块 `data` 与单块 `offsets`，逐任务直写，最后构造成单个 `DataBlock::VariableWidth` 调用一次 `into_arrow` + `restore_validity`（完全跳过中间 `Vec<ArrayRef>` 和 `concat_decoded_arrays`）。
- 校验：
  - 为 `StructuralCompositeDecodeArrayTask` 多页直写补单元测试（覆盖 `Utf8`/`LargeUtf8`/`Binary`/`LargeBinary`、含 null 与空字符串、混合压缩/非压缩页回退）；
  - 跑通 `cargo test -p lance-encoding`、`cargo fmt --all -- --check`、`cargo clippy -p lance-encoding --tests -- -D warnings`；
  - 编译 `release-with-debug` Python 扩展（记录 sha256），对 `wide-unique`、`wide-unique-8k`、`wide-mixed` 做全量 scan + take 逐行 exact round-trip 校验（含 null、空串、短串）。
- 测量：用与实验 A **完全相同的矩阵与数据集**再跑一遍：
  1. `wide-unique`（135 页）：`take(128)` 与 `take(1024)` 的连续 20 次（冷第 1 次 + 热稳态 + 峰值 RSS）；
  2. `wide-unique-8k`（44 页）：`scan`（耗时 + 峰值 RSS）与 `take(128)`（耗时 + 峰值 RSS）；
  3. `wide-unique`（135 页）：`scan`（耗时 + 峰值 RSS）。

---

## 交付与 `$issue-branches` 发布要求

1. **纯主分支不动**：确认 `perf/10526-wide-value-page-split` 仍指向 `d0020f429`。
2. **试验分支发布**：按 `$issue-branches` 规范推送包含实验 A、B 两个独立提交的试验分支（记录两个提交的完整 SHA）。
3. **Review 分支更新**：在 `review/10526-wide-value-page-split` 新增：
   - `review/issue-10526/linux-64cpu/decode-followup.md`：包含四列完整对比表（`base (1p)` / `final (135p/44p)` / `exp-A (exact reserve)` / `exp-B (page bridging)`），明确列出：
     - `take(128)` 冷第 1 次、第 2 次、稳态（#6–#20）耗时与峰值 RSS；
     - `take(1024)` 冷第 1 次、第 2 次、稳态（#6–#20）耗时与峰值 RSS；
     - `wide-unique-8k scan` 与 `wide-unique scan` 耗时与峰值 RSS（重点核对 `+25.86%` RSS 超标项的变化）；
     - 两个扩展的 sha256 与提交 SHA；
     - 明确结论：`#10526` 保持独立提交时 PR Evidence 应该如何准确表述冷/热 take 表现，以及实验 A / B 各自作为 follow-up PR 的实测收益。
   - `review/issue-10526/linux-64cpu/decode-followup/`：保留脚本、原始 JSON/JSONL 与 `SHA256SUMS`。
4. **暂不改写 `pr-draft.md` 里的主 PR 承诺，也不合入实验代码到 `#10526`**；全部推送完毕后汇报结果与分支/SHA 链接。
