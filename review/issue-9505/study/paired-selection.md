# 配对格选择记录

首轮及普通列补充存活检查结束后，2026-10-18 22:20 UTC 登记 `run-pairs-v1.sh`。源码、扩展、fixture、harness 沿用 `all-v1`，新增完整依赖补采在配对前完成。以下 87 次 execute 均固定 reader、Rows writer、8 GiB cgroup、hot cache；除 reverse 为 256 MiB pool，其余为 1 GiB。每格三个 block，候选顺序由冻结 harness 随机化；比较项在 plan 中预先登记。

| 工作负载 | 配对候选 | 选择理由 |
| --- | --- | --- |
| F16 | B, P, D, DB, DP | 小输入、大旧表：检验统计、late 与固定选边的独立及组合代价 |
| Wn | B, P, D, DB, DP | 宽遗漏旧字段：比较可完成者的 early/late 成本及组合开销 |
| Ws | P, D, DB, DP | 输入自己携带大字段：检验 repartition/缓冲代价；B 已资源失败 |
| R_admission | B, D, DB | 三者可完成，检查 EOF 准备与组合在大输入下是否引入回退；P/DP 已资源失败 |
| N_dense, V_dense | CTX, B, P, D, DB, DP | 完整对照普通遗漏列的 high-coverage 成本，以及 source 准备和 P 策略能否改变该成本 |

U 保留新的统一基线存活测量，不重复失败，也不拿其单样本计算配对加速。F64 的 D pool 失败与 DB 成功已经回答 target keys/address 增长是否仍导致失败；失败时间不参与比值，不为 DB 单边多跑三次构造胜率。late_jump 的任务是资源边界与完整值检查，真实小值→连续大值顺序另由定向 Rust 测试确认，不宣称其单次 API 时间差稳定。

第一格冷读取为 `cold-ordinary-v1` 的 CTX/D × V_dense。两次 mincore 逐文件 after 均为 0 resident pages，execute read_bytes 均为 159,899,648 B。CTX/D 分别 0.912659/0.965261 s，采样 RSS 1008.60/609.18 MiB。它没有推翻 warm 存活检查所提示的时间/内存交换，因此不铺开冷读矩阵，也不将该 n=1 比值作为稳定冷读性能结论。冷读记录仍保留，最终是否补配对取决于 warm 三轮是否出现需要冷读解释的新决策边界。

正式配对之后才运行辅助 analyze，避免诊断和计时并行。任何新候选、配置、消融均需新 freeze/plan；本记录不授权更改已有计时合同。
