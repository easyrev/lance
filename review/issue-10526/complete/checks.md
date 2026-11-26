# 选定提交的代码检查

提交 `16e3c99b1faa6014c17e33331f35cce726302243`。Cargo target 和临时目录在磁盘。Workspace Clippy 也使用 `release-with-debug`，与交接单的统一构建 profile 一致。

| 命令 | 退出码 | 日志 |
|---|---:|---|
| `cargo fmt --all -- --check` | 0 | [fmt](raw/check-fmt-pure.log) |
| `cargo test -q -p lance-encoding -p lance-file --profile release-with-debug` | 0 | [联合测试](raw/check-tests-pure.log) |
| `cargo clippy -p lance-encoding --tests --profile release-with-debug -- -D warnings` | 0 | [lance-encoding Clippy](raw/check-clippy-encoding-pure.log) |
| `cargo clippy --all --tests --benches --profile release-with-debug -- -D warnings` | 0 | [workspace Clippy](raw/check-clippy-workspace-pure.log) |

联合测试记录 2,614 个编码和 476 个文件单元测试通过，16 个文档测试通过，4 个测试忽略。联合测试输出中有 `rust/lance-io/src/object_store/hf_throttle.rs:34` 的 dead-code 警告。Workspace Clippy 记录 `rust/lance-linalg/build.rs` 的可选 fp16/bf16 内核未启用提示。两个源文件在 base 和选定提交之间均无改动。
