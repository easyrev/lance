# 可移植源码片段

这些文件保留本轮机制说明引用的最小源码段，供离开原工作机后复核。它们是分析附录，不改变 source/binary/fixture freeze，也不构成额外执行实验。

- [HashJoin build 分配](hash-join-build.md)：DataFusion physical-plan 54.1.0，保留批次、hash table、concat 和 bitmap 相关行。
- [统计与 CollectLeft 选择](join-selection.md)：DataFusion physical-optimizer 54.1.0，bytes/rows 与 collect 规则。
- [RoundRobin batch 分派](round-robin.md)：physical-plan 54.1.0 的 repartition/mod.rs 原 779–791 行，其中 783–791 行是被引用分支。
- [Lance Take 地址分组](lance-take.md)：固定基线 0a0d327082988018a25f56147d3b6d02f6c79ecc 的 take.rs 原 284–345 行，与冻结 U 的完整文件 SHA 相等。

[metadata.json](metadata.json) 记录原文件完整 SHA、原行号、每段原文 SHA，以及 DF crate 版本与 Cargo.lock package checksum。DF 片段来自本机 crates.io registry cache；它们的 full-file hash 不是远端依赖源码重验。基线与候选冻结锁文件包含相同版本和 package checksum。原文件路径仅作为来源元数据保留，阅读片段不依赖这些路径。DF 代码版权属于 Apache Software Foundation 及贡献者，按 Apache-2.0 提供。
