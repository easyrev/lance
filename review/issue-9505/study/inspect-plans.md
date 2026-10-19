# 已落地 analyze 文本提取规则

`inspect-plans.mjs` 使用 Node 标准库，只读传入文件并向 stdout 输出 JSON；不会导入 Lance、打开 dataset、运行计划、修改 ports 或访问远端。可传新 `analyzed-plan.txt`，也可传旧 `candidate.jsonl`。例如在仓库根目录执行：

```sh
node output/unified-9505-20261019/inspect-plans.mjs output/unified-9505-20261019/diagnostics/*/analyzed-plan.txt > /tmp/merge-plan-inspection.json
```

输出 `files[].plans[]` 保留文本 SHA256、行号、父子节点和所有原始指标字符串；旧 JSONL 的 plan 还保留 `phase`、`record_line`。同一旧 JSONL 同时包含 explain 与 operator_metrics，必须选择 `phase=operator_metrics`，不能把第一个 plan 默认当执行指标。新 txt 每个文件只有一个 plan。`joins[]` 指出物理 HashJoin 的 left build、right probe 及各侧叶子；source/target 需结合 URI、provider 和投影判断，不根据行数命名。`exchanges[]` 指出节点位于某 HashJoin 的 build/probe 子树，或保留 `null` 待人工定位；`scan_nodes`、`materialization_nodes`、`writer_nodes` 是对应的 node ID。所有缺失字段保留为缺失/`null`，不补零。

必须按以下规则解释结果：

| 检查对象 | 提取位置与需要核对的内容 | 不能据此推出什么 |
|---|---|---|
| 完整执行 | 每个 plan 的 `execution_complete` 恒为 `null`。另对照真实 execute 的结果、oracle、错误；diagnose 内再核对 writer 的 updated/inserted/deleted counters 是否符合该 fixture | `validated_diagnostic`、有物理树、无顶层异常、writer output_rows=0，都不构成完整执行证明。analyze helper 在 `rust/lance-datafusion/src/exec.rs:805–809` 丢弃 stream 的 Err item；writer 通常不输出 RecordBatch，output_rows=0 本身也不是失败证明 |
| HashJoin | `joins[].node` 对应节点的 mode、join_type、projection；左右叶子及中间 Projection；`build_input_rows`、`build_input_batches`、`build_mem_used`、`build_time`，probe `input_rows`/`input_batches`/`join_time` | build_mem_used 不等于 RSS；不能根据 build 行数独自判定 source/target；统计精度 Exact/Inexact/Absent 和 EOF 事实若文本未给出，则仍未知 |
| Repartition / Sort | 对应节点的 partitioning、input_partitions、上下游字段；`spill_count`、`spilled_bytes`、`spilled_rows`、fetch/repartition/send 时间 | TMP 文件大小接近 source bytes 不能代替节点归属。spill 为累计量，TMP 是同时存活量；analyze 部分执行时零 spill 不能证明完整 execute 不 spill |
| scan | 叶子的 URI、projection、row_id/row_addr；output_rows、rows_scanned、fragments/ranges_scanned、bytes_read、iops、requests、peak_read_tasks | 旧 LanceRead 的 output_batches/output_bytes 常为零，即使扫描实际完成；不能用 rows/0 推批量或把零输出字节说成没读数据。配置 batch rows 和实际批量分布若未打印，保持未知 |
| late Take | MergeCondition 的 take/payload、条件、snapshot（若有）；condition_take_rows/arrow_bytes、payload_take_rows/arrow_bytes、payload_reused_condition_values | Arrow bytes 不等于存储 I/O；内部 TakeBuilder 没有自动成为独立 TakeExec。调用次数、每批地址局部性、页重复读取，不能从这几个聚合 counter 重建 |

Lance `format_plan` 在 `rust/lance-datafusion/src/exec.rs:920–924` 已调用 `aggregate_by_name()`。因此这份文本只能提取节点级汇总，不能恢复逐 partition 指标或最大单 partition 使用量。`elapsed` 属性是该子树的时间跨度，指标 `elapsed_compute` 是累计计算时间；两者都不应当作完整 execute wall time相加。

数字换算保留 `raw` 并附 `approximate_value`、`unit`、`rounded`。DF 54.1 的 `output_bytes`、`spilled_bytes` 使用二进制大小格式，文本 `250.0 MB` 表示约 `250×1024²` bytes；generic Count/Gauge（包括 build_mem_used、bytes_read、payload_take_arrow_bytes）使用十进制缩写，`262.1 M` 表示约 262,100,000，`2.10 B` 表示约 2,100,000,000，不能把这个 B 当作 bytes 单位。缩写会四舍五入，不能拿还原值与 raw JSON 的精确 bytes 做严格相等断言。百分比、NOT RECORDED 等不能可靠换算的内容只保留 raw。依据为本地 DF 54.1 `datafusion-physical-expr-common/src/metrics/value.rs:1047–1077` 和 `datafusion-common/src/display/human_readable.rs:29–75`。

已对两份旧冻结证据做纯文本提取校验：`output/first-principles-9505/evidence/runs/smoke-Ws-Ccore-rewrite_columns-b0/candidate.jsonl` 的 operator_metrics 有 target LanceRead build、stream probe、probe-side Repartition spill 25 行/250 MB；`smoke-Wn-Clate-rewrite_rows-b0/candidate.jsonl` 有 memory source build、LanceRead probe 和 payload_take_rows=25。校验通过，未执行任何 Lance 工作负载。旧结果仅验证解析格式，不继承为本轮 Rows、候选或资源状态的证据。

对下一批实际诊断，先检查 `ignored_lines` 为空、HashJoin child_count_valid=true，再提取 F16 的 build 来源与保留量、Ws 的具体 spill 节点、N/V 的 build/probe 变化与 scan/Take 工作量。即便 counters 与预期一致，完整性仍由独立真实 execute 验证；这份提取器不会把诊断状态升级成成功执行。
