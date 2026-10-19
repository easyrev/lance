# 最终结论判定清单

状态：**结论模板，尚未填入本轮性能判断。** 本文件只把 [decision-protocol.md](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/decision-protocol.md) 与 [cost-mechanism.md](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/cost-mechanism.md) 转成可核验的问题，不新增事后阈值，不替代主任务结果。三个原候选是 B/P/D；CTX 用于归因，DB/DP 用于检查组合。允许最终答案是“某个基础值得继续，但尚无满足全部目标的默认方案”。

## 0. 写结论前的门槛

- [ ] 每个被引用结果对应本轮冻结 base、port、实际加载 binary、fixture 与初始 snapshot；历史结果、test-only snapshot、diagnostic、正式 execute 分开。
- [ ] 先看全部字段/NULL/操作计数/版本 oracle。任何确定错误值、重复或丢失行、失败操作提交，否决该 revision 的性能资格，不能被快样本补救。资源错误与 OOM 要重开 dataset 验证原快照；它们是容量边界，不是成功执行。
- [ ] 加速比只取同 workload、writer、input form、资源和 cache 合同内双方成功的同块配对。按本轮协议报告三轮随机配对的原始比值、中位值、范围和绝对时间；样本少或方向不稳就写“尚未区分”，不作总体统计保证。失败时间不进入加速比。
- [ ] 配置 pool、实际执行 pool、Take 软目标、RSS/cgroup 峰值分别说明。U 配置了 1 GiB 不代表其执行 pool 有界；受控资源错误也不等于完成业务。
- [ ] 冷读沿用“尝试驱逐后的本地读取”标签，结合 mincore、实际 read_bytes；没有对象存储证据就不外推网络请求收益。性能实验通过、综合方案更优、值得上游接纳分别落判。

## 1. 三个候选分别在哪些场景占优或失败，原因是什么？

每个候选按“通过/失败范围 → 同合同配对 → 实际计划/资源证据 → 尚不能解释的部分”写，避免按平均名次回答。

| 必须回答的边界 | 支持的观测与归因 | 不足以支持的说法 |
| --- | --- | --- |
| B 的 source 准备 | EOF、provider 统计、最终 build 侧与 join mode 确实改变，并在总 execute 中抵偿预读成本；跨限则确认 prefix+tail 与完整结果 | “source rows 小，所以一定 CollectLeft”；DF 有 bytes 时优先按 bytes，EOF 不保证 collect；未 EOF prefix 不能当完整统计 |
| P 的固定 source build / scan | 同合同下主宽表完成、实际 build=source，scan/batch/峰值与候选差异一致；同时保留 R_admission 的 reverse 成败 | “pool 失败是安全成功”；“总时间下降全来自去掉 RoundRobin”；“小 source 成功证明任意 reverse 可用” |
| D 的 late payload | D/CTX 隔离窄 target、late Take、条件复用和分块整体；Wn/Ws、N_dense/V_dense、late_jump 分开判断 | U/D 的全部差异归给 late；条件复用、chunk sizing 各自收益已被独立证明；一次存活证明硬内存上限 |
| 组合的相互作用 | DB/D 检查 EOF 准备；DP/P 检查 P 执行策略下的 late；F64 查窄 target key/address 增长，reverse 查固定 source 的容量代价 | B/DB 是纯 late 消融；DB/DP 只差预读；N_dense/V_dense 只差预读 row 阈值 |

原因必须能被诊断推翻：若推测 DB 通过换 probe 侧改善局部性，先核实 actual-source 计划，再看 Take 地址集合/页重访；target scan 未承诺保序，Take 单次内部已有排序。没有这些证据就标“合理推断”，不升格为已证实。[局部性判别](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/locality-hypothesis.md)

## 2. 保留、删除、组合什么；何时选择 DB、DP 或分流？

以下是选择**下一步基础**的条件，不是已得到的结果，也不是所有条件都通过后即可声称普遍最优。

| 观察到的结果组合 | 可支持的下一步 | 必须保留的限制 |
| --- | --- | --- |
| DB 在 D 的大 target 容量边界上完成，actual plan 证实完整 source 统计提供了更小 build 的出口；同时 reverse、宽值和 dense 的代价可接受，DB/D 的有效配对显示准备成本值得付出 | 以 DB 为基础，保留 EOF 统计 + late + 共同 context，继续 Auto | 未 EOF 仍未知，变长统计不保证可靠；无 batch/time 上限、超大首批及未记账缓存仍是 B 的边界。不能称为已实现原设计的 admission/StatsGuard |
| DP 在主场景有稳定收益或更好的实际容量，DP/P 表明 late 的额外成本有回报；DB 的 Auto/预读在关键场景仍明显失效，且应用可明确限定为适合 source build 的输入范围 | 以 DP 为该范围的基础，保留 P scan policy 与 D late | 固定 source build 的 reverse 风险继续存在。若 R_admission 失败，只能支持有边界的方案，不能选作满足原全部目标的通用默认；整表均宽 sizing 仍可能把窄 scan 切得过小 |
| DB/DP 只在不同负载上占优，或 early 在 dense/cold 占优而 late 在 sparse/wide 占优 | 保留互补机制，提出条件分流或显式选择的后续方向 | 只有能在决策时取得且成本可接受的证据才可作自动 guard。source key 数不能代替实际更新物理行/页覆盖；不能用事后 oracle 实现“选择赢家”。当前冻结代码没有性能 selector，不能写成已交付分流 |
| CTX/B/P 已获得主要收益，而 D/DB/DP 的额外层次只带来噪声级差异、明显回归或新的容量失败 | 选择更小基础；不因已经写完就保留 late 或组合 | 若双方容量不同，先区分“旧方案无法完成”的价值与“同成功格更快”；不能只看时间删除解决必要容量问题的机制 |
| 所有方案仍各有关键失败，新增排序/StatsGuard/native 等仅有设计推断 | 报告尚无满足全部目标的默认方案；保留最小有证据部分和反例 | 不把待实现设计计入当前候选成绩，不继续扩矩阵来冲淡失败 |

**足以否定当前无性能 guard 的默认 late 的结果：** 同合同、实际进入 late、正确性等价的 D/CTX 或 DP/P 配对，在有代表性的 dense/cold 范围出现稳定且有实际影响的回退，尤其超过本轮原有 10% 调查门槛，并且没有该格明确需要的容量/资源收益来解释所接受代价；或 late 在 early 能完成的资源格可复现地失败。此时不能继续声称“所有 eligible scalar partial Rows 默认 late 都值得”，应收窄适用范围、保留 early/显式选择或改变实现。若决定为资源收益接受吞吐代价，必须明确列出取舍，不能抹去回归。

10% 沿用协议的调查触发标准，不是见到一个样本就自动拒绝的统计检验。单个慢样本、三轮方向不稳、小绝对差值、未核实 cache/实际计划，均不足以定案。反例否定的是当前 revision 或默认范围，**不自动否定所有 late 设计**；例如 DB 的换边/局部性可能缓解 D 的某项回归，需真实组合证据。若仍无法在执行前安全识别昂贵范围，不能以“将来加 guard”保留无条件默认。

## 3. 当前最佳方案是否满足原共同目标？

- [ ] 小 source / 大 target：F16 及必要的 F64 是否真正 execute+commit，source/target 实际投影和 build 状态是否符合解释？窄 key/address 仍随 target 行数增长，不写成任意规模有界。
- [ ] reverse：真实未知且大于预读门槛的 source，在指定资源合同下是否完成？提高 pool、预先 materialize 或把资源错误算成功均不能替代原 gate。
- [ ] 宽且不等宽字段：旧 payload 与 source 新值两种压力是否分别处理？D 不能删掉 source 新值，扫描磁盘均宽不能保证峰值分配。
- [ ] dense、条件与 NULL、重复键、错误、retry：正确性与退化边界是否保留？late_jump 机制测试是否证明真的先见小值再连续见大值，而不是凭 source 顺序推断？
- [ ] 资源边界：实际 pool 生效、进程与 cgroup 结果、未记账缓冲和 oversized batch/单值限制是否分清？不承诺 join 自动 spill 或 RSS 硬限。
- [ ] 对原蓝图的差异是否明确：本轮没有新增 native scan、StatsGuard、按 pool 派生且带 batch 上限的 source 准备，也没有 early/late 强制 API 或收益 selector。缺少某个原设想组件不自动否定业务目标可由更小实现达到，但不能声称完整原设计已经实现或验证。

每项只填“已证实 / 合理推断 / 证据不足”，并附结果/源码位置；未跑场景填未验证，不填通过。

## 4. 复杂度、跨模块影响和默认范围是否与收益相称？

- [ ] 使用生产与测试分列的维护成本，不能把 tests 总行数冒充生产执行器。当前冻结计数：DB 生产 Rust `+647/-172`，DP `+671/-169`；D condition 节点独占 `+437/-96`。只在源码 hashes 仍匹配时引用，完整统计见 [cost-audit.json](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/cost-audit.json)。
- [ ] 分别说明维护对象：B 的 prefix/EOF/replay/FirstSeen；D 的 action→地址→条件值复用→nullable payload→分块→snapshot；P 的选边/并行/scan budget 及 indexed/Columns 外围。相近净增行数不代表相近风险。
- [ ] 收益必须对应实际进入的代码路径。D 只覆盖合格 current-v2 Rows scalar 遗漏字段；full source、Columns、scalar-index、blob/不支持的遗漏类型不能计入 late 收益。
- [ ] 默认范围与证据匹配：仅本地 hot sparse 的明显收益支持局部适用性；dense/cold 或错误恢复关键边界尚未验证时，不足以支持广泛默认。反过来，多格稳定容量/时间收益可以支持维护这条生命周期，但不能跳过正确性门槛。

## 5. 独立 PR、互补 PR、合作还是反馈证据？

| 推荐形式 | 足以支持该形式的证据 | 不应越过的范围 |
| --- | --- | --- |
| 独立、聚焦的 PR | 有清晰独立问题与可隔离补丁，收益及默认范围经对应对照验证；不重复 #10077 已承担的同一修复，必要回归和接口合同完整 | 不把 DB/DP 的整体胜出自动转换成整包替代 PR；当前没有发布授权 |
| 互补 PR | DP/P 或其他有界证据证明 late 为 #10077 策略补足了独立价值，能清楚保留其外围责任并说明依赖顺序 | 不用 Rows 非索引结果声称替代整个 #10077；公共 helper/context 若有重叠须明确拆分 |
| 与 #10077 合作 | 最佳机制需要共同修改相同 planner、context 或 scan policy，单独提交会重复或冲突；双方方案取舍有完整反例和同基线证据 | 先提出具体保留/替换模块及证据，不假定维护者已同意或一定接纳 |
| 反馈补丁与证据 | 暂无稳定综合赢家、默认 late 被反例约束、必要边界未解决，或额外复杂度回报不足 | 这是有效技术结论，不包装成已完成通用 killer 方案或已获上游认可 |

**主 Rows 矩阵不能替代的 #10077 责任：** indexed 未覆盖 fragments 的 scan budget；候选 Union→Coalesce 行为；indexed Full→Left/Inner 收窄后的 source-only 插入、重复候选、复合 key/NULL；covering-index Take；legacy/Columns sort 的 pool/context 与 column patch 文件/lineage 语义。P/DP integration 有四阶段，但只有前两阶段检查 heap growth，且宽 payload 已在 source；现有名为 indexed composite NULL 的测试实际只建部分 key index、走非索引回退。外围测试通过数字不能扩大为所有外围资源/性能保证。[覆盖审计](/Users/salamanca/workspace/personal/Lance/output/unified-9505-20261019/test-coverage-audit.md)

最终回答按用户五问依次落判，每问分清已证实、推断和不足。至少同时给出：当前推荐基础及适用范围、应删除/保留的机制、尚未满足的共同目标、复杂度是否值得、建议贡献形式。三个判断单列：**性能实验是否通过；综合方案是否更优；证据是否足以建议上游接纳。** 第三个只能是有依据的建议，不能由本地通过推出维护者结论。
