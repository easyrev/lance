# #7363 与 condition 内置 payload 的责任比较

本轮测量入口只覆盖无条件 UpdateAll、非空地址、当前 Rows 数据格式的 join/payload 阶段；它不代表通用优化规则已经实现。source/ 保存固定基线 TakeExec，inputs/ 保存 #7363 的描述、作者反馈和历史 commit 4a31cea。代码量不直接等于维护成本。

| 责任 | D/DB 的 condition 内置实现 | #7363 rule + TakeExec |
|---|---|---|
| 缩窄目标扫描 | merge planner 明确记录遗漏字段，condition 扩展输出 nullable payload | 找到真实 target scan 与字段起源，改写 scan、join projection、父 projection，重映射索引和属性 |
| 取值生命周期 | 每分区串行软分块，按片创建 TakeBuilder，保留输入 backing 与条件数组直到该片完成 | 复用已打开 FragmentReader，多个 map_batch 并发，内部排序/去重/按 fragment 读取；并发窗口仍需考虑 |
| 插入 NULL 地址 | Insert/Nothing/Delete 只构造 nullable 占位，payload 只对 UpdateAll 读取 | 当前 TakeExec 不支持 source-only NULL 地址；历史 spike 增加 compact/scatter 与 nullable-extra schema，还须覆盖 all-NULL 与 with_new_children |
| 条件更新 | 先取条件列、拒绝后不取 payload，重叠条件列复用缓存 | 放在 condition 前会提前取被拒绝行的 payload；放在 condition 后需要知道 action，并让条件值穿过节点，否则可能再取一次 |
| 删除与无操作 | 不为这些 action 读取最终旧 payload | 普通非空 rowaddr 不表示要写新行；通用 Take 仍会读取，需要 action mask 或分流，且保留 writer 所需原 rowaddr |
| 重复 key / 地址 | 最终重复匹配检查在 writer；D 的取值不是全局每个物理行恰好一次 | Take 已支持一批内地址去重并恢复重复输出，但不处理 merge 的跨批 source 去重和重复匹配策略 |
| 错误与重试 | 错误随执行流传播；每个 attempt 必须重新匹配并刷新 dataset snapshot / 地址 | Take 的 IO 错误随流传播；缓存与 dataset Arc 属于本次执行流，不能把旧物理计划或地址跨 snapshot 复用 |
| DF 升级 | 维护专用 exec 的 schema、distribution、projection、reset 等契约 | 同时维护通用 Take 的新增行为和 rule 对 join/scan/projection 布局、优化顺序的匹配契约 |
| 启用范围 | 现 D 的资格是类型/语义资格，未按收益选择 | 原 rule 的 width/storage gate 会排除窄 int64，但所有变长字段仍可能被选中；没有可靠 match selectivity 就仍不能排除 dense variable 成本 |

CoalesceTake 已折叠相邻 Take，含允许的 CoalesceBatches 中间层；它不跨 HashJoin 决定列起源，也不跨分区统一排序或合并不同批次的稀疏地址。scanner 的 MaterializationStyle 主要处理单 scan/filter 内的读取时机，不能自动知道 join/action 的存活行；其宽度/storage gate 可以复用，但不能把估计值当收益证明。

#7363 的历史实现只匹配左侧直接 FilteredRead 的 join，并跳过 join filter。统计修复常把 source 放左、target 放右，分布优化还会插入 Repartition，因而不能原样承接 DB/F16 已验证的组合。提前应用 rule、增加右侧对称改写或识别交换层都可能解决匹配范围，但会增加计划与统计的维护责任。仅在 merge call site 调用可缩小其他查询受到的影响，并不免除这些局部契约。

本轮之所以运行最小 spike，是 TakeExec 的 reader cache 和批次并发构成实际路径差异。两者都保留 join 输出的稀疏 rowaddr、页覆盖和输出顺序恢复问题；更换节点不会自动产生跨 batch 的全局局部性。三轮 generic/D 的时间比在 Wn 为 2.276、N 为 0.302，而 N generic/early 仍为 1.941，CPU 与 RSS 也更高。当前证据不支持直接替换 D 或全面移植 rule；复用取值内核只能作为另一个有具体目标的局部改动评估，不因节点更通用就继续扩大范围。
