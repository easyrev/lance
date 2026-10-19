# Unified #9505 harness 独立审查

审查者：match_scan_design。范围：只读审查 fixtures、oracle 和 runner；不修改被审文件，不运行 benchmark、build、SSH。本文是审查记录，不代表运行验证通过。

## 第一轮：fixtures.py / legacy_fixtures.py

第一轮审查时 runner 尚未出现；后续实际入口为 `harness.py`。以下是当前源码审查状态，行号以对应检查时文件为准。

### 已修复的第一轮问题

1. **成功路径提交版本检查已补齐。** `fixtures.py:139-141` 的 string_null 分支和 `fixtures.py:206-208` 的一般分支，均对独立 initial snapshot 检查有变化时版本前进。
2. **string_null 的 producer 记录已补齐。** `fixtures.py:87-92` 包装原始 string source，为每批记录 rows/bytes。
3. **变长列 NULL 已补齐。** `fixtures.py:59-61` 分别按 17/19 取模生成 Utf8/LargeBinary NULL；`fixtures.py:192-200` 用单独 tag 区分 NULL 与空字节。

### 已确认的区分力与边界

- N_dense 的 180,000/200,000 和 V_dense 的 90,000/100,000 为 90% 唯一物理行更新；整数 linspace 在该密度下不会重复 key，再确定性打乱顺序。两者继承 `dense=False`，因此是大量唯一 source keys 的高覆盖，不是少数重复 target keys 的高覆盖。后者由原 dense_safe fixture 的 row_marker 区分。
- oracle 根据持久化 row_marker/id 重建每列预期值，同时检查 marker 全局唯一、完整覆盖和 merge stats。c0/c1 更新值为负数，旧值为非负确定性值，更新不是 NoOp；未更新列逐值检查，能识别同 key 的旧 payload 错配。
- V_dense 已覆盖独立 NULL Utf8/LargeBinary；string_null 另覆盖 NULL source 值、NULL condition/key。
- V_dense 的 text 和 binary 在均为非 NULL 时逐行长度相同，长度在行间变化；late_jump 的短 text 与大 binary 才具有明显列间宽度差。不得把前者描述成每列独立宽度分布。
- late_jump 把 marker 0..63 的 binary 设为 32 B，其后为 1 MiB，source 升序且一批。此设计提供宽度突增输入，但 join/repartition 可能改变物化次序。仅有 spec、source 日志或总 payload_take_rows 不足以证明 materializer 实际先观察小值、随后按旧估计读入大值；需要计划/定向机制证据，或保留“触发尚未证实”的限定。
- P/DP 仍按整表物理字节估算 target scan batch，即使 DP 的 target projection 很窄。宽度突增 fixture 的平均物理宽度会让该 scan 先产生很小的 probe batches，可能在 materializer 之前限制突增规模。相同 source batch 不能证明各变体承受相同物化 chunk 压力。
- unchanged validator 重新打开实际 dataset，并从独立 initial-snapshot.json 读取初始版本，即使 worker 未保存 metrics 也能验证失败后状态；这避免了旧 snapshot handle 的假验证。

## 第二轮：harness.py

### 已修复的第二轮问题

1. `harness.py:586-587` 已将每格 validator identity 与冻结的 validator imported identity 比较。
2. `harness.py:517-531` 已聚合 source 的 yielded batches/rows/Arrow bytes，正确区分这些量与 EOF polls/downstream retention；`harness.py:578-581` 要求正常返回时 rows 等于 spec.source_rows 且不存在末行截断。失败格保留已观察消费量，不强求读完 source。

### 剩余非阻断解释事项

- `harness.py:579-583` 如果 API 已成功提交，但 producer 日志验收失败，会改走 validate_unchanged；后者会因实际成功提交而失败，最终记成 failed_atomicity_check。该分支不能直接解释成执行过程中发生了部分提交；应先检查原 metrics.status、source_consumption_error 和日志。这不影响日志完整且正确的正常成功路径。
- 新增 diagnose 走 `analyze_plan`，输出放独立 diagnostics，汇总也单列；它不成为 merge_seconds 的配对样本。诊断要求对应生存格已成功，避免为已知失败格再次运行重型 analyze。
- 正确性门检查 variant、workload、binary/source identity，未要求 write_mode 一致。若仅执行 Rows 正确性门，不能宣称 Columns 也通过了同一门；Columns 性能格自身仍会执行完整结果 oracle。

### 源码支持的证据边界

- `execute` 在 builder.execute 周围计时，lazy reader 消费包含在 merge_seconds；materialized 输入的 read_all 在该区间外，另计 input_materialization_seconds 与 input_and_merge_seconds。fixture、clone、缓存准备和结果 oracle 都在计时区间外。失败分支的 merge_seconds 另包含异常分类和 traceback 格式化的短暂开销。
- 每格 worker 记录真实 import path、extension SHA、版本；run_cell 将执行身份与 freeze 比较。freeze 还覆盖源文件、环境、build log 和 harness hashes。源码身份与 binary 身份分别记录，不能单靠源码 hash 推导 binary 已按其构建。
- failure validator 在独立 cgroup 中重开 latest dataset，检查独立初始版本及所有值；OOM 以 execution cgroup 的 oom_kill 增量识别。执行和验证的峰值、事件保存在独立资源记录中。
- cache_state 在 fixture hash 检查及 clone 后运行，对初始 manifest 内所有 .lance 文件执行 fsync/fadvise 和 mincore；worker 在 execute 前没有显式数据 hash/全量预读。标签为 evict_attempt，解释承认 fadvise 是 advisory，没有把调用返回视作缓存已冷。每文件 mincore 是顺序观测，不是整个文件集同一时刻的全局驻留快照。
- no_builds 只在每格开始和阶段开始检查。串行锁只覆盖同一 ROOT 的 coordinator，不能阻止其他目录启动 benchmark/build；运行期间无构建依赖主任务独占调度，不能从该 guard 单独推导连续隔离。
- oracle 的 hashes 按扫描输出顺序累积，允许 writer 合法重排行；这些 hash 不是跨变体的 canonical row-order hash。正确性以逐行标识、全字段预期和完整覆盖断言为准，不应直接比较不同变体的原始 hash 判定差异。

## 审查结论

在上述已修复内容的源码版本中，没有发现阻断调度的确定 invocation/schema 错误。此结论只来自静态审查；不包含 Python 编译、真实 fixture 生成、cgroup/mincore 能力检查或 benchmark 运行。`CODE_FILES` 包含 RUNBOOK.md，冻结前该文件必须由作者交付。本轮源文件仍在作者收口，最终身份以主任务 freeze 中的 hashes 为准。
