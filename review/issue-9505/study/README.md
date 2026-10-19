# Lance #9505 / #10077 同基线调查

本轮已完成代码移植、构建、定向正确性测试、资源存活检查、87 次随机顺序三轮配对、23 次辅助计划诊断及 ECS 现场文件身份审计。**结论：DB 是有价值的组合基础，但当前没有满足全部共同目标的通用默认方案；建议先与 #10077 合作反馈补丁、反例和证据，不直接提交整包替代实现。**

本轮 161 次真实 execute：153 次成功、7 次 pool 资源失败、1 次 cgroup OOM；八次失败均独立验证原快照全部字段不变。87 次正式配对全部通过完整值及操作计数 oracle。诊断单列，不计入成功提交或计时样本；失败和慢样本全部保留。

## 阅读顺序

1. [REPORT.md](REPORT.md)：五项技术选择结论、场景结果、机制取舍、维护成本和未满足目标。
2. [cost-mechanism.md](cost-mechanism.md)、[diagnostic-findings.md](diagnostic-findings.md)：源码机制与实际 build/probe、扫描、交换、Take 证据。
3. [paired-report.md](paired-report.md) / [JSON](paired-report.json)：全部三轮原值、范围、配对比率、CPU、RSS、累计 I/O 和新文件量；[配对选择](paired-selection.md)解释没有继续铺开冷读矩阵的原因。
4. [VALIDATION.md](VALIDATION.md)、[test-coverage-audit.md](test-coverage-audit.md)：实际加载二进制、构建、NULL/条件/重复键/重试/大小突变测试及覆盖边界。
5. [audit-final-v1.json](audit-final-v1.json)、[final-pairs-audit.md](final-pairs-audit.md)、[final-audit-review.md](final-audit-review.md)：现场审计与独立复核；[REPRODUCE.md](REPRODUCE.md)给出复算和重跑入口。

## 冻结版本与移植

本轮最初核对时，上游 main 为下面的 U，#10077 仍开放、head 为 P；原 GitHub API 响应保存在 [inputs/](inputs/)。之后冻结这些身份，不滚动更换基线。

| 对象 | 冻结来源 | 本轮快照 |
| --- | --- | --- |
| U | `0a0d327082988018a25f56147d3b6d02f6c79ecc` | 未修改的共同基线 |
| B | `793e4e27119540a17ae37ce78d4f5f4d52060a93` | [统计准备补丁及移植说明](ports/B/) |
| P | `9e1ebc2e816a7195b56757ebe269e74989fc30c7` | [#10077 完整移植](ports/P/) |
| D | `50e216972e1558ce253bece5db462d8241fde96a` | [deferred payload 移植](ports/D/) |
| CTX | D 的 context/factory 接线，early payload | [上下文对照](ports/CTX/) |
| DB | D + B，共享 D context | [实际组合实现](ports/DB/) |
| DP | D + P，保留 P 策略及外围改动 | [实际组合实现](ports/DP/) |

P 的真实 parent / 与 U 的 merge-base 为 `8d77df617e85687567e9529fbc5520f793783e78`。历史 `f8859373`、`90d98187` 和旧目录名 P 不冒充本轮版本。每个 `ports/<variant>/` 都有完整修改文件 `source/`、可应用于 U 的 `implementation.patch`、`port-notes.md` 和 SHA256。纯 B/P 无人工生产代码增强；组合冲突和 test-only 调整单独记录。

U/D 复用经本轮重新核验的优化构建，其余五个候选新建独立 checkout、target 和 venv，按仓库流程使用 `release-with-debug --locked`。所有构建均早于性能采样。完整源、扩展、依赖、harness、配置和 fixture 身份见 [freezes/all-v1.json](freezes/all-v1.json)；依赖后补采集的边界见 [dependencies-audit.md](dependencies-audit.md)。

## 比较与交付边界

主比较固定非索引、reader 输入、Rows writer、8 GiB cgroup；通常配置 pool 为 1 GiB，reverse 为 256 MiB。各候选实际执行 pool 和并行策略保留，不能把配置 pool 当作进程内存上限。CTX→D 隔离 late 整体；U→D 同时包含 context/factory 修正。Columns 仍是业务替代选项，本轮没有把其历史数据混入 Rows 排名。

现场审计为 passed：16 份 plan、184 格记录、无 reference、无缺格、无错误或警告，并核对实际源码、扩展、构建日志及 fixture 文件。它复核已保存的 oracle，不重新扫描各个 dataset；逐字段读回已由每次执行后的独立 U worker 完成。不是全 workspace / 全语言 CI 通过声明。

ECS 完整工作根：`lance-ecs:/mnt/lance/unified-9505-20261019`。本地本目录保留代码、脚本和原始记录；大 fixture、逐格 dataset、venv 和编译产物留在 ECS，不装入证据包。原冻结证据未改写。原始统一设计、任务书和归档入口副本在 [inputs/](inputs/)，未实现的替代草案明确单列，不计入本轮成果。
