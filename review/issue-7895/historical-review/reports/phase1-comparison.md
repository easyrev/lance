> Historical report. Status statements describe the stage when this report was written. See the [review index](../README.md) for the published branch context. Only links were adapted below. The [original report](../evidence/phase1-comparison.md) remains byte-identical.

对照材料仅为指定 commit `ef7264d49a8b7b48b5a51dcc889624160d58f602` 中的 `prototypes/issue-7895/phase1.txt`。下载自该 commit 的 raw URL，原文保存在 `phase1-allowed-report.txt`，SHA256 为 `bbd1ee24d68b50046b0935cb88983d001f1cd55a3beecd50bbfdbcf85d5b84f5`。没有读取其他分支产物或排除的旧 PR，也没有跟随报告中的其他 PR 链接。

读取发生在 2026-10-11 13:23 UTC，晚于完整候选快照（13:14）、本轮扩展首轮定向验证和首轮独立审查报告（13:20）。对照前补丁为 `pre-phase1.patch`，SHA256 `dca79bf7508e03703a304ca64e6fd1b2879de7e5f79dd5050b15601641e9c2c1`。报告基于更早的 upstream，因此其测试通过记录和实现均未作为本轮验证结果。

| 报告中的观察 | 本轮独立核对 | 对候选的影响 |
| --- | --- | --- |
| reader 转换会丢失可重读能力；现有 provider 支持重试 | 对照前已在当前源码确认，并实现统一 registry 与可执行读取工厂 | 保持独立方案；不缩回只支持原生 Dataset 的实验 |
| 无 spill 文件不代表没有 replay 缓冲 | 对照前的外部探针已校准：256B one-shot 创建 replay 目录但不落盘；候选 Lance/Arrow 实际重试不创建该目录 | 保留外部观测，不添加报告中的生产 tripwire 或计数接口 |
| 版本、扫描配置、计算值与 encounter order 需要共同约束 | `source-contracts.md`、首轮测试及独立探针已分别验证；未知配置和 opaque Scanner 回退 | 保持工厂的稳定 schema、值与顺序契约 |
| 第三方扩展和其他写入入口未在旧实验完成 | 本轮在读取报告前已实现并验证第三方实际重试、单次写入、未提交执行和分析路由 | 不继承旧实验的范围限制或接口稳定性结论 |
| 刷新目标后，需要重新判断新匹配键 | 增加竞争 upsert：同一提交重写已有行并插入源中的另一键；九种输入重试后均无重复键，统计从插入3/更新1变为插入2/更新2 | 唯一由本次对照引起的实质修改是扩展现有冲突测试；没有生产代码改动 |
| 性能比较需要控制计划与工作负载 | 本轮已在对照前准备匹配构建、原始计划、交替重复矩阵及保留全部样本的汇总器 | 最终性能结论仍以本轮优化构建的实测为准 |

最初尝试只在 commit hook 中 append 一个匹配键。九种输入均出现第二次提交调用，但未重新计算已有 merge 结果；这不构成所需的语义重试夹具，不能靠 commit hook 次数证明来源重新执行。失败记录保留为 `python-phase1-refresh-first.log`。修订为竞争 upsert 后，已有行重写强制执行冲突处理，九项通过记录为 `python-phase1-refresh-upsert.log`。新夹具沿用本轮原有数据、输入矩阵和公共 commit hook，不复制旧实验实现。

共用 analyze helper 的错误传播修复来自本轮独立审查，在读取报告前已确认并开始修复；它不是 Phase 1 对照发现。新增错误回归在旧候选上重现四项失败，记录为 `python-analyze-errors-before.log`。修复和本次新增测试都必须纳入后续构建、验证与复审。
