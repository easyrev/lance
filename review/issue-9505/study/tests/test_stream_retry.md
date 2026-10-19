# 一次性 partial source 的真实重试

`test_stream_retry.py` 是独立补充测试，不修改冻结 ports、现有 `test_merge_semantics.py` 或性能 harness。只含一个测试：4 行、2 fragments、V2.2，source 为两个单行 batch 的 `RecordBatchReader`，遗漏 nullable Utf8 与 Boolean 字段。

测试先在 v1 建立两个 stale builder，再用独立 dataset handle 做真实 Rows 更新，将 key=0 的旧 payload 改成 `concurrent`，同时改变 Boolean，并断言 row address 已移动。零重试 builder 必须报 `Attempted 0 retries`，随后完整 v2 值、版本历史保持不变；最多允许一次重试的另一个 stale builder 必须成功。结果检查全部字段、两次更新/无插入删除、仅新增一个提交版本，以及 v1/v2 历史快照不变。两个 source generator 均只产出各自两批并到达 EOF 一次。

它补充的是流式入口与 late retry 的交界：DB 的小 reader 经 B 的 EOF 准备成为 MemTable；DP/D 使用既有可重放 source 路径。已有 Rust `test_partial_merge_retry_refreshes_payload_and_row_address` 直接断言 `num_attempts == 2`，但其 `execute_batches` 绕过 DB 的 reader 准备。这个 Python 测试不 mock commit，不用线程抢时序，不把仅设置 retries 参数当作真实冲突证据。

Python 当前 `build_stats` 只返回 inserted/updated/deleted，**没有 `num_attempts`**（共同基线 `python/src/dataset.rs:681–688`）。这里通过同一 stale snapshot 的零重试失败、最多一次重试成功、移动后的 row address 和新 payload 断言建立真实重试证据；不声称直接测得 attempt 数。generator 事件证明原 source 只生成一次，也不被当作 attempt counter。

该用例没有覆盖 B 的跨 131072 行或 100 MiB fallback、磁盘 replay spill、FirstSeen 或 retry 内存峰值。两行 source 足以验证 EOF 准备路径，不能冒充跨限重放覆盖。资源与吞吐仍由冻结 harness 独立测量。

在已按 `python/AGENTS.md` 完成 `make install`/对应扩展构建的 D、DB、DP checkout 的 `python/` 目录分别运行，保留各自扩展身份和独立日志：

```sh
uv run --no-sync pytest /mnt/lance/unified-9505-20261019/tests/test_stream_retry.py -q
```

本文件准备时只做源码/API 核对，未执行 Python、SSH、构建或测试。真实结果由主任务记录；不得把设计断言当作已通过。
