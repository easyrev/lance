# 本轮假设与停止条件

共同实验基线继续冻结为 0a0d327082988018a25f56147d3b6d02f6c79ecc；已查询的 main 为 8c233c2e6aa6948524f352e5e4cd52bd1364f6ff，领先六个提交。#10077 head 仍为 9e1ebc2e816a7195b56757ebe269e74989fc30c7。完整响应在 inputs/。旧结果只作为已经回答的问题和选择实验的依据，不算新测量。

1. H1：manifest 的压缩文件字节能否可靠修正宽 target 的 build 选择？新建高度压缩 Binary/Utf8 最小 fixture，实际比较原 schema 估计、使用全部数据文件大小的保守 manifest 估计、局部撤回不可靠 target rows/bytes 并从 source-left 开始的保护。完整 MemTable 和未知 reader 单列。使用全部文件大小避免通过按列比例分摊故意压低 manifest 估计；它仍不是解码上界。若反例击穿估计，停止推广磁盘字节估计；固定宽 reverse 只用于检查局部保护没有全局禁用换边。无需为失败格计时。
2. H2：恢复 P 的分布优化，再缩小 session batch_size，能否把实际缓冲和并行恢复到可接受范围？完整 merge 使用 P 的 source-left 与原 scan budget，分别开关 repartition_joins / RoundRobin，保持 join_reordering 的比较合同明确。另以 Ws 的同一 source 值做直接 RoundRobin 边界探针，区分“交换之后的 coalesce 大小”与“交换之前的大 batch 分发”。单批与相同值的多批形式分开。若缩小 batch 仍无有效分发，最多做一个在交换前按实际支持字段字节拆分并紧凑复制的小原型，不扩大到通用 batch admission。
3. H3：现有 TakeExec 的 reader cache 与并发是否产生不同执行路径？先审查 #7363 原始 spike 与当前 TakeExec。只实现 update-only、非空地址的 join + payload spike，比较原 D condition 代码与现有 TakeExec；不实现整套通用优化规则。若进行性能配对，明确是 join/Take 阶段加共同 sink，不与旧完整 merge API 时间混算。N 的强制 generic-late 是机制消融；#7363 原宽度 gate 本来会排除这些窄整数列。NULL 地址、重复地址、条件与重试合同单独判断。

先诊断、完整值校验和资源检查；只有结果可改变技术判断的成功格才三轮随机配对。所有配置、源码、实际 Rust 二进制与 fixture 独立冻结，使用新目录。旧 harness 的只读函数和 fixture 可复用，但不修改其文件。DF reservation 高水位、进程 RSS、cgroup、临时文件与累计 IO 分开；所有失败保留，错误必须传播，不使用忽略 stream Err 的 analyze helper。
