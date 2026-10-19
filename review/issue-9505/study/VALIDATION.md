# 正确性、身份与边界

## 实际完成的工作

固定 `release-with-debug --locked` 构建成功，opt=3、debug=2、thin LTO、16 codegen units，未覆盖仓库 profile。独立 checkout、target、运行根和 cgroup 与历史证据分开。构建完成后才开始诊断和性能实验；每格启动前复用旧 `no_builds` 检查。新 lib test 可执行文件 SHA256 为 `f397efd2d71f160f5ca94f0775f093d7ba34fb5e8f2b167c1b4dca82625fb34d`。compiler artifact、实际启动命令与路径均保存。

53 格记录：26 次前置诊断（含两次 plan-only）、27 次正式随机配对。按任务分开：

| 任务 | 成功执行 | 受控 pool 错误 | 仅计划 |
|---|---:|---:|---:|
| 真实 merge writer + commit | 16 | 4 | 2 |
| RoundRobin + IPC sink | 11 | 0 | 0 |
| join/payload + IPC sink | 20 | 0 | 0 |

合计 51 次真实执行，47 次成功、4 次预期反例资源错误、0 cgroup OOM。不能称为 47 次完整 merge。四次失败均完整读回验证旧版本及每个字段未变；两次 plan-only 也验证旧 snapshot。正式配对 27 次全部成功并通过全字段 oracle，六组比率均含三个 block。

完整 merge 的 source 输入、资源、计划、计时范围、merge counts、commit version 与每字段独立读回均在各格保存。新压缩与固定 reverse fixture 使用生成值逐字段比较；复用 Wn/Ws/N/R 的原可信 oracle。RR 输出全部 source 字段逐行 hash 比较、ID 完整无重复，逐分区行数与批数同时比较。Take 阶段由独立 U Python 扩展读取原旧值，验证所有遗漏字段及 source 新值、非空 rowaddr、action 与 sentinel。每个输出 IPC 的 SHA/大小由 validator 保存。

错误沿 `try_next().await?` 传播；没有使用吞掉 stream error 的 analyze helper。execution_error 由研究 driver 写入记录，不能仅据 lib test exit=0 认定 merge 成功；runner 要求独立 oracle 通过，报告根据明确 status 分类。失败与慢样本没有删除或计作加速比。

## 定向既有单测

性能实验全部结束后，使用同一 frozen binary、无 LANCE_HYPOTHESIS_SPEC、单测试线程执行：[脚本](scripts/unit-tests.sh)、[日志](logs/unit-tests.log)。

- TakeExec 16 项：输出 schema/statistics、重复与乱序重复地址、顺序、stale 地址、错误入口、with_new_children 等。
- merge deferred_conditions 19 项：NULL 条件 verdict、source/target 条件、条件列复用相关、重复 source key、delete/nothing 等原有语义。
- merge spilled_lineage 19 项：已有 spill/retry/repeated operation 语义。
- 六项精确选择的 provider/batches/source-statistics/错误传播/spill_for_retry=false 测试。

共 60 项通过，0 failed/ignored。它们验证 P 基础的既有行为及当前 Take 契约；不证明新 guard 已覆盖每种条件/类型，也不证明尚未实现的通用 NULL/action Take 或完整 #7363 rule 通过。原 D/DB/DP 的完整条件、retry、突变测试继续由旧冻结证据承担，没有把旧测试算作本轮新测试。不声称 workspace CI、Clippy、Python lint 或上游接纳通过，本轮没有创建/更新 PR。

## 身份与归档审计

[audit-final.py](scripts/audit-final.py) 在 ECS 哈希核对：实际 frozen binary 及 compiler 原件、完整 workspace source/locks、修改文件快照、原 patch、frozen harness、配置、源数据 IPC、生成与复用 fixture、validator 实际扩展、源文件导出与真实 ECS registry 的 DF/Arrow 代码，并复核旧证据 SHA256SUMS。所有 53 格的 plan spec、embedded metrics/oracle、cgroup、启动路径、freeze SHA 和阶段输出文件哈希都检查；不重新执行全部字段 oracle。结果为 [audit-final.json](audit-final.json)。初次审计缺少上传到 ECS 的本地 source export，失败日志保留；上传只读副本后重跑，不涉及实验源码或 workload 重跑。

冻结时 `git diff HEAD` 未包括继承自 P 的 untracked integration test `rust/lance/tests/merge_insert_memory_bound.rs`。它的字节从一开始就在 full_tree_identity 及 P-base.patch 中，--lib 不会编译该 integration target。未改写原 freeze 或 patch，后补 [reconstruction-supplement](reconstruction-supplement.json) 和 [full-reconstruction.patch](full-reconstruction.patch)。[重建核对](reconstruction-check.json) 从干净 U 导出、应用完整补丁、逐个比较所有原冻结 workspace source/lock 哈希；此补充解决打包完整性，不伪造构建前已有 standalone patch。

最终 SHA256SUMS 用于本地紧凑包的内容核验；大型 fixture、逐格 dataset、IPC 输出、实际 binary 和编译缓存留在 ECS，不装入本地包。最终新行文件大小、累计读写、累计 spill、TMP 峰值与内存采样是不同量，不能互相替代。

## 仍然不足的证据

本轮 H1 current 为统一 scan/context 下恢复原 Auto 初始方向的策略对照，不是重新跑 U 的原始二进制。H2 同一 P 基础逐项配置消融，未拆开两个分布 flag 的各自独立收益；H3 是 UpdateAll 非空地址的阶段比较，未实现通用规则或 writer。所有数据来自本地热缓存，不外推冷读/对象存储。三轮可识别这里的大差异，不能证明普遍比例。

pool reservation 高水位、采样 RSS 和 cgroup peak 均保留；共享页、解码、source backing、Take 与 coalescer 临时值没有成为统一硬 pool 上限，采样也会漏短峰。新 splitter 在输入批之后工作且单行可超过目标，不提供严格内存可靠性。`statistics-before-selection.json` 的 mask_only 诊断附带布尔 `target_masked` 误写为 false；实际 wrapper、统计与计划均明确双 Absent。本问题只影响附带标签，未改写冻结 driver，也未据该标签推导结论。
