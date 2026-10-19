# Python source 边界补充验证

`test_merge_semantics.py` 是独立 pytest 文件，可用于本轮所有候选；没有修改冻结 ports。它通过真实 `RecordBatchReader`、`merge_insert` 和 commit 路径运行，不 mock 实现。

## 已核对的 API

以 U `0a0d327082988018a25f56147d3b6d02f6c79ecc` 的 `python/python/lance/dataset.py`、`python/src/dataset.rs` 和 `python/python/lance/lance/__init__.pyi` 为准：支持 `use_index(False)`、`write_mode("rewrite_rows")`、`conflict_retries(0)`、`when_matched_update_all(condition)`；运行时 merge 错误经 PyO3 映射成 `OSError`。返回 operation 统计只有 inserted/updated/deleted 三项。

当前 Python API 没有 `source_dedupe_behavior` 或 FirstSeen setter。此文件不将默认 Fail 当成 FirstSeen，不跳过后声称已覆盖，也不添加候选专用 binding。FirstSeen 跨预读停止边界仍是未覆盖项；现有 Rust FirstSeen/retry 测试是不同的覆盖范围。

## 三个测试

所有测试使用 4 行、2 fragments 的目标；source 省略 nullable Utf8 和 Boolean 字段。首批包含 131073 行，超过冻结 B/DB 使用的默认 DF 131072 行限制，约 2 MiB 的两个 Int64 列即可触发 row-bound fallback，不需要构造超过 100 MiB 的大对象。

1. `test_tail_source_error_after_row_bound_preserves_snapshot`：跨限首批后先成功读取一个 tail batch，再产生源错误。断言原始错误消息、生成器事件，以及最新版本、版本历史和全部字段均未改变。
2. `test_duplicate_modification_across_row_bound_fails_without_commit`：prefix 与 tail 都修改同一 target key，断言默认 Fail 的 ambiguous-merge 错误及没有提交新版本。
3. `test_only_actual_update_counts_across_row_bound`：prefix 中匹配行全部被条件拒绝，同 key 的 tail 才满足条件。断言恰好一次 update、零 insert/delete、全部字段与 NULL 保留、只有一个新版本、旧 snapshot 仍保持原值。

源错误测试不禁止临时未提交文件；数据原子性的 oracle 是新 manifest 不出现，完整 snapshot 不变化。生成器事件证明源内容的读取次序，但不声称记录了异步 reader 的每次 poll。对于 U/D/CTX 等没有 B 准备机制的候选，同样输入验证跨 batch 的错误和重复修改语义；只有 B/DB 可依据冻结实现把 131073 行首批解释为预读 fallback。

本文件没有覆盖 100 MiB 字节跨限、慢 producer、无限空 batch，或 FirstSeen 跨停止边界。这里没有重复实现 retry 测试。

## 运行与状态

在主 agent 已按仓库 `python/AGENTS.md` 完成 `make install` 的每个候选 Python 环境中，从其 `python/` 目录运行：

```sh
uv run pytest -q /absolute/path/to/test_merge_semantics.py
```

准备时只读取基线 API 并写入文件；没有在本地运行 Python、pytest、格式化器或构建。运行结果待主 agent 的 SSH 验证。
