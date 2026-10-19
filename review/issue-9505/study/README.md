# Lance #9505 / #10077：源码假设验证

已完成：独立优化构建，26 格诊断与 27 次三轮随机配对，60 项定向 Rust 测试，实际源码/二进制/fixture/原始记录审计。51 次实际执行中 47 次成功、4 次受控 pool 错误；另有 2 次仅计划。阶段探针与完整 merge 分开统计，失败均验证旧快照不变。

**结论：本轮没有得到覆盖共同目标的新默认方案。** manifest 压缩字节不能安全替代 Arrow 宽度；session batch_size 不能拆开超大输入批；直接换用 TakeExec 没有全面胜过 D 或避开 dense 回退。保留共同 context、可信统计与范围受限的 late 价值，优先与 #10077 协作；不建议整包替代 PR 或继续移植完整 #7363 rule。源码推导、实测与不足证据分别标注。

1. [REPORT.md](REPORT.md)：六项技术决策、反例、三轮比率和最小修复路径。
2. [SOURCE-FINDINGS.md](SOURCE-FINDINGS.md)、[ARCHITECTURE.md](ARCHITECTURE.md)：DF 选边/缓冲机制，D 与 #7363 的产品责任。
3. [results.md](results.md) / [JSON](results.json)：全部 53 格及三轮原值/比率；[runs/](runs/)保存 spec、真实 plan、operator metrics、reservation、进程/cgroup、IO 与全字段 oracle。
4. [VALIDATION.md](VALIDATION.md)、[audit-final.json](audit-final.json)：60 项测试、1196 个源码/锁文件、真实依赖、496 个阶段输出文件及旧 3149 个归档文件的核验；[重建校验](reconstruction-check.json)通过。
5. [REPRODUCE.md](REPRODUCE.md)、[DECISIONS.md](DECISIONS.md)：复算、构建/执行入口、比较合同和停止条件。

| 身份 | 固定对象 |
|---|---|
| 共同基线 | `0a0d327082988018a25f56147d3b6d02f6c79ecc`，DF 54.1.0 / Arrow 58.4.0 |
| 当前查询 main | `8c233c2e6aa6948524f352e5e4cd52bd1364f6ff`，未切换实验基线 |
| #10077 head | `9e1ebc2e816a7195b56757ebe269e74989fc30c7`，仍开放 |
| 新实验实现 | U 上 P 移植 + test-only driver；[完整可重建补丁](full-reconstruction.patch)、[实际编译快照](snapshot/) |
| 新实际可执行文件 SHA256 | `f397efd2d71f160f5ca94f0775f093d7ba34fb5e8f2b167c1b4dca82625fb34d` |

源码、compiler artifact、实际 binary、harness 和 fixture 身份在 [freeze-v1.json](freeze-v1.json)、[paired-freeze.json](paired-freeze.json)、[fixtures.json](fixtures.json)。原 freeze/patch 保持不变，继承 P untracked 测试文件的打包补充见 [reconstruction-supplement.json](reconstruction-supplement.json)。[source/](source/)与[inputs/](inputs/)包含固定源码、上游原始响应和历史规则；[vendor/](vendor/)仅为旧 harness 的原字节副本，历史测量不冒充本轮样本。

完整 ECS 根：`lance-ecs:/mnt/lance/hypotheses-9505-20261019`；checkout：`/mnt/lance/checkouts/hypotheses-9505`，分支 `experiment/9505-source-hypotheses-20261019`。本地包排除大 fixture、dataset、IPC 输出、binary 和编译缓存，这些留在 ECS。旧冻结证据通过原 SHA256SUMS 核验。没有提交 PR、推送分支或向上游发布评论。
