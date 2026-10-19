# late payload 前按物理地址排序：只读替代设计预研

状态：**尚未实现，尚未构建或实测。** 本文记录只读分析，不能作为性能改善、正确性或内存上界的验证证据。只有真实 dense workload 结果确认 D 的随机 Take 存在显著回归后，才考虑独立实验；当前冻结候选保持不变。

## 分析对象与源码位置

- 统一基线 U：`0a0d327082988018a25f56147d3b6d02f6c79ecc`。
- D：`50e216972e1558ce253bece5db462d8241fde96a`，即 narrow target、late payload、共享 bounded context，已移除 join admission selector。
- 本文核对的 D `condition.rs`、`logical_plan.rs` 使用 `ports/DB/source/` 中逐字节继承 D 的文件；本文所引 DB `merge_insert.rs` 行号对应本轮冻结移植产物。其他 Lance 文件以 `git show U:<path>` 为准，不使用当前工作分支的实验源码代替基线。
- DataFusion：本机 Cargo registry 中锁定的 `datafusion-physical-plan-54.1.0` 与 `datafusion-physical-optimizer-54.1.0` 源码。

## 可能收益及其边界

全局按 `_rowaddr` 排序值得作为 dense 回归后的独立实验，但不宜直接设为默认路径。收益主要来自跨 batch 聚集物理位置相近的更新，使连续输出批访问相邻地址；代价是完整输入屏障、排序、可能的 spill，以及与 HashJoin 竞争同一个 pool。

U 的 `rust/lance/src/dataset/take.rs:210–356` 已区分连续地址、已排序地址和无序地址。连续地址使用 `read_range`；已排序地址按 fragment 读取并拼接；无序地址会自行排序、按 fragment 分组，再映射回原顺序。因此，只对现有的小 batch 排序，主要节省映射成本，无法消除下一批再次访问同一 fragment/page。全局排序才可能改变跨批访问局部性；高覆盖且地址连续时还可能进入 `read_range` 路径。这是机制推断，尚无本轮实测证明。

## 可插入的边界

D 的条件 gate 和 payload Take 在同一个 `Evaluator::apply` 内：

- `ports/DB/source/rust/lance/src/dataset/write/merge_insert/exec/condition.rs:445` 求 deferred update condition。
- 同文件第 482 行开始 payload Take，第 511 行复用已读取的条件值。
- `ports/DB/source/rust/lance/src/dataset/write/merge_insert/logical_plan.rs:326–339` 只构造一次同时处理条件和 payload 的 `MergeConditionExec`。

因此，通用的“所有最终 action 已决定、payload 尚未读取”目前没有独立物理算子边界。拆分时必须处理条件值缓存：把缓存列带入排序会增加宽度，不携带则可能重复读取。排序放在条件前还会改变 volatile 表达式的求值顺序，不能直接宣称与排序后求值完全等价。

最小实验建议先限于 Rows、partial schema、有 deferred payload、`UpdateAll`、无 inserts、无 target-only deletes。该形状没有 deferred target condition，可在 payload-only `MergeConditionExec` 前排序。实验计划形状为：

```text
join + action projection
    -> CoalescePartitions (only when needed)
    -> HardCapBatchSizeExec
    -> SortExec (_rowaddr ASC)
    -> payload-only MergeConditionExec
    -> existing Rows sink
```

作为隔离实验，可在完整物理优化之后局部替换 materializer 的输入；共同入口为 `ports/DB/source/rust/lance/src/dataset/write/merge_insert.rs:2906–2912` 创建物理计划之后、返回计划和 TaskContext 之前。execute/analyze 必须经过同一变体入口，并继续共用该 attempt 的 TaskContext。首轮不同时加入 no-op 过滤、自动写模式选择或新策略阈值，以便判断排序本身的贡献。

## 裸 SortExec 可能被优化器移除

D 在追加 payload 时重新创建 `EquivalenceProperties`，不保留输入 ordering，见 `condition.rs:269–278` 及 `condition.rs:606–615`。Rows sink 本身只要求单 partition，不要求输入 ordering，见 U 的 `rust/lance/src/dataset/write/merge_insert/exec/write.rs:1180–1187`。

DF 54.1 `datafusion-physical-optimizer/src/enforce_sorting/mod.rs:497–523` 会移除没有所需 ordering、又被上层算子消解的排序。因此，仅在 planner 中放入裸 `SortExec` 不能证明实际执行时仍有排序。优化后局部变换可用于最小实验；若日后形成正式实现，应给 materializer 明确的 `required_input_ordering` 和 partition contract，让优化器生成或保留排序。实验必须断言最终实际计划包含需要的 Sort / SortPreservingMerge，不能只检查逻辑 sort。

## 内存、spill 与宽 source 成本

DF 54.1 `datafusion-physical-plan/src/sorts/sort.rs:1253–1274` 在未满足排序要求时消费完整输入，随后才输出。第 716–749 行先留 merge reservation，再为完整输入 batch 申请空间；即使允许 spill，当新 batch 的 reservation 无法容纳时仍会失败。第 779–797 行的 batch reservation 考虑 backing allocation 与 sliced size，不能把 Arrow slice 当作已经缩小的底层分配。

U 的 `rust/lance-datafusion/src/exec.rs:379–395` 使用同 pool 的 `min(pool / 3, 40 MiB)` sort reservation，以及 `TrackConsumersPool(FairSpillPool)`。新 sort 和正在执行的 HashJoin 会竞争 pool。加入可 spill 算子不等于保证原先成功的查询仍成功。

现有 Columns 写回路径在 `ports/DB/source/rust/lance/src/dataset/write/merge_insert.rs:1807–1833` 使用 25 MiB `HardCapBatchSizeExec` 后再按 `_rowaddr` 排序，可参考其保护机制。U 的 `rust/lance-datafusion/src/exec.rs:1148–1167` 和第 1221–1237 行明确说明：超限 batch 需要深拷贝；超限单行会被拒绝；仍不保证任意 pool 或竞争条件下成功。把该 cap 加到 Rows 默认路径会引入新的资源失败边界，不能不加说明地推广。

“窄 mutation rows”仍包含全部 source 写入字段。`logical_plan.rs:240–247` 保留全部 source 列，排序会缓存、复制并可能 spill 这些值，即使遗漏的 target payload 尚未读取。只排序地址和 source ordinal、之后再取 source 值，需要额外的可重读存储及生命周期管理，超出最小实验范围。

## 语义、重试和索引影响

整行重排必须一起携带 `_rowaddr`、`_rowid`、created-at lineage、source sentinel、action 和 source 值，不能只重排地址。

- 默认 Fail 仍应只检查最终 Update/Delete 的重复 row id。U `exec/write.rs:154–261` 的 sink 在实际 action 上执行重复检查；不能在条件判定前去重，否则会改变“一个候选被条件拒绝，另一个候选实际修改”的行为。
- 当前 v2 FirstSeen 在 source 边界按顺序去重后才 join，见 U `merge_insert.rs:1199–1293`。后置排序不会重新选择非 NULL key 的赢家，但必须保留这条顺序边界，不能把排序移到 source dedupe 前。
- NULL `_rowaddr` 表示 source-only 行。若扩展到 inserts，应明确 NULL 排序位置，并继续为遗漏字段填 NULL。当前最小实验不包含 inserts；不能据此声称已验证完整 outer join 形状。
- Rows sink 按实际输出次序捕获并放置 lineage，见 U `exec/write.rs:219–228`、第 780–832 行及第 1038–1045 行。整行排序本身不要求改事务格式，但既有行的 row id、created-at 和更新结果必须通过实际结果断言验证。
- 重试必须对新 snapshot 重新 scan、生成地址、排序和 Take。U `merge_insert.rs:3558–3566` 在每次 attempt 重扫 provider，第 3617–3618 行替换 dataset；不可把携带旧 target 地址的排序结果跨 attempt 复用。
- 保留现有 Rows sink、affected rows 与事务/index maintenance 路径。排序不构成跳过冲突检测或索引维护的理由，索引更新成本也不会因此消失。

Columns 路径已经在自身写回中排序，且不读取遗漏 payload；该实验应限制在 D 的 Rows late-payload 路径，避免重复加入排序或改变显式 write mode。

## 已知 ordering 能否省排序

DF `SortExec::execute` 在 `sort.rs:1211–1223` 根据输入 `EquivalenceProperties` 检查 ordering，已满足时直接透传。多个有序 partition 可使用 SortPreservingMerge；单 partition 已满足 ordering 时可以省掉实际排序。

只能依赖最终物理计划明确提供的 ordering contract。不能从 source key 有序推断 `_rowaddr` 有序：fragment 重写、稳定 row id 与物理地址的区别、hash repartition 都可能破坏推断。D 添加 payload 后丢失 ordering 的现状也需要纳入正式设计，不能用数据看起来有序代替证明。

## 若实测支持，再验证什么

比较 D 与最小排序变体，至少包含 dense shuffled、dense already ordered、一个 sparse 反例及一个宽 source 反例。记录总时间、真实 Take 请求和物理读取字节、sort spill、峰值 RSS。`payload_take_bytes` 统计 Arrow 返回数组量，不能代替物理 I/O 指标。

小型正确性测试需要实际 collect，核对跨 fragment 的值与 lineage、重复修改失败、源尾部错误和重试刷新；若扩展支持条件及 outer join，再覆盖条件拒绝、NULL 地址、inserts、target-only deletes 和 FirstSeen。最终计划断言只能证明算子存在，不能替代执行验证。

以上均为待验证建议。本次没有修改源码、构建候选或启动性能实验。
