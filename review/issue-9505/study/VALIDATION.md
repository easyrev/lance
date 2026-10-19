# 实际构建与测试记录

本页只汇总本轮实际执行。`ports/*/port-notes.md`、测试设计说明和独立 review 保留各自准备时的状态；不能用这些说明代替下面的运行日志。所有候选构建及下列测试、统一 harness 的前置正确性、资源检查、第一格冷读、87 次三轮配对和 23 次辅助诊断均已完成；技术选择见 [REPORT.md](REPORT.md)。

## Python 扩展与语义检查

所有命令通过对应 checkout 的 `uv run --no-sync` 执行。pytest 与扩展哈希检查处于同一个 Python 进程；每次运行前后哈希一致。选择原 `test_dataset.py` 的 merge_insert 测试，再加入 `tests/test_merge_semantics.py` 的三项源流边界检查。不同候选继承的原测试数量不同，不把数量差异当作覆盖优劣。

| 版本 | 实际加载扩展 SHA256 | 本轮 pytest | 驱动退出码 |
| --- | --- | ---: | ---: |
| U | `5c9e85d8804aeac54f030db6a7a0b8f02373e89c2f106777bbb2647660a1d65a` | 41 passed | 0 |
| B | `a8776de4b107f2db5b696defb9675cb0dfade7516fe7b119f681ad7c6c085034` | 45 passed | 0 |
| P | `681988e5e0a51e70a02918304c0a54c2e8f530bef8b107743e84af548db5c604` | 41 passed | 0 |
| D | `ec2c898d18d4ee20c611cfb93c7642118fde354107aee5d1cd8d0c4296ab1c2c` | 41 passed | 0 |
| CTX | `6e18f93d0d2d916a9b119e2387f0f52d8c03c7296be08ffcdd149bc6975758c7` | 41 passed | 0 |
| DB | `1b28b5def10d4e004b90820b470b11191574353761d6280a680f73db601a79db` | 45 passed | 0 |
| DP | `1eff3e28735a0cb8166e6c650c3eb5660fd4187477156a471e11d41cd0346409` | 41 passed | 0 |

对应原始日志为 `logs/<V>-python-tests.log` 和 `logs/<V>-python-exit-code`。U 首次驱动出现过 pytest 返回 0、shell 返回 2 的异常；完整日志及说明保存在 `logs/U-python-initial-tests.log`、`logs/U-test-selection-note.md`，未删除。表格使用随后完整重跑的 41 项、驱动 0 结果，不把首次驱动异常归为候选功能错误。

U、D 使用经本轮重新核对源码和扩展哈希的既有优化构建。B、P、CTX、DB、DP 为本轮新构建。新 checkout 均先 `make install`，随后 `make build`，采用仓库 `release-with-debug` profile 和锁定依赖。

独立补充 `tests/test_stream_retry.py` 已在 D、DB、DP 通过（各 1 passed，分别 0.22/0.16/0.05 秒）。它用真实竞争写移动行地址并改变遗漏旧值，先验证零重试失败且旧快照不变，再验证一次重试额度下的一次性 reader 正确完成，并检查全部字段及三版本快照。源生成一次与 Python 返回操作计数均有断言；Python 不暴露 `num_attempts`，不把生成次数当作尝试次数。测试 SHA256 为 `82e30feb86cf8fca252471b489291978c34b3c91b0ccb219843406d9a8cd2fab`，各扩展前后身份及完整结果见 `logs/<V>-stream-retry.log`。

## Rust 检查

- DB、DP 的隔离测试快照已通过 `cargo fmt --all -- --check`；完整 merge 单元测试分别 356/359 passed，均为 0 failed、0 ignored。测试运行分别 1.33/0.93 秒。测试快照额外应用 `tests/late-jump.patch`，不修改基准扩展源码；两种大小值突变用例和真实 retry 刷新地址/旧值测试均通过。
- P 的原 `merge_insert_memory_bound` integration target 本轮通过：1 passed，测试运行 2.09 秒，构建 profile 为 `release-with-debug`。原始输出见 `logs/P-integration.log`，源码和产物摘要另存于 `logs/P-integration-*`。
- DP 的同一 integration target 通过：1 passed，测试运行 1.53 秒，退出码 0。原始输出见 `logs/DP-integration.log`。

大小值突变测试在单分区直接驱动物化器，两个组合均通过单次和反复突变：小值之后第一次大值输出包含 8 个 64 KiB 字符串，至少 512 KiB，达到 128 KiB 软目标的至少 4 倍；之后输出缩为单行。它证明观测后的调整有效，也直接证明软目标不是单批分配或进程峰值上限。API 场景的 RSS/cgroup 峰值仍须独立测量。

P 集成测试的实际证明范围见 `test-coverage-audit.md`：不是完整逐键、逐字段 oracle，也没有为全部阶段断言堆增长。它不替代本轮统一 harness。原始测试及构建失败、队列取消记录均保留；`logs/queue-v2-note.md` 解释只调整等待队列和编译并发的过程。

## 诊断与性能证据边界

只有统一 harness 中成功的真实 `execute` 加独立完整字段 oracle，才用于判断该实验正确完成。生产者日志记录的是已经 yield 的行数、批数和 Arrow 字节，不是下游完成标记。资源失败须验证旧快照完全不变。

基线的 `analyze_plan_with_context` 会忽略 stream Err，现有 sink 指标也无可靠完成标记。因此 `validated_diagnostic` 仅代表该 harness 的诊断合同通过，不能证明整个诊断执行成功。只在独立 execute 已成功的同合同格使用诊断计划辅助解释，并核对扫描、join、action、Take 等可预期计数；详见 `DP-integration-review.md`。

独立 `audit-results.py` 已在 ECS 通过语法检查。零结果预检如预期返回 incomplete（退出码 2），见 `logs/audit-initial.log`；这不是实验通过。最终使用 `--verify-files` 的现场审计已返回 passed，驱动退出码 0，见 [audit-final-v1.json](audit-final-v1.json) 与 `logs/audit-final-v1.log`。16 份 plan 共 184 格：161 次实际 execute、23 次诊断、0 reference、0 missing、0 errors、0 warnings；实际源码、扩展、构建日志和 fixture 文件哈希均匹配冻结记录。审计复核已保存的 oracle，不重新扫描 dataset，也不将资源失败当作成功。

161 次 execute 包括 153 次完整值与计数验证成功、7 次 pool 资源失败和 1 次确认 cgroup OOM；失败后原快照全部字段与版本均经独立校验保持不变。87 次正式配对均成功，全部原样本保留。诊断驱动退出码 0；其 23 次 `validated_diagnostic` 仍受上文 analyze API 的完成性限制。
