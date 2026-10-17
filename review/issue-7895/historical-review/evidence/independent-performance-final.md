最终独立审查结论：候选 `26632629ca162cdbfd82dabad1d80e3e6c92b364` 已具备交给维护者 review 的证据。首轮发现的 analyze 吞错问题已经关闭；本轮原始性能资料审查没有发现新的阻断缺陷。可信收益是符合契约的来源绕过 replay 缓冲及临时文件。实测也包含小输入延迟、部分重试 CPU 和 RSS 的回退，不能把候选描述成普遍更快或更省内存。

本报告承接 `independent-review-first.md`、`independent-review-revision.md` 和 `independent-performance-script-audit.md`，不覆盖其中的历史发现。资料边界保持不变：未读取排除的旧 PR、其实现或派生资料，未读取 `/workspace/lance` 的源码。首轮独立审查之后只读取获准的 `phase1-comparison.md` 来核对修改来源，未将 Phase 1 的通过记录当作本轮证据。性能判断来自脚本、仓库源码、原始 JSON、探针事件、实际执行计划和自行重算的结果。

产物对应关系已重新核对。baseline 为 `4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9`，candidate 为上述最终 commit，补丁 SHA256 为 `9694eb0eaf38d30a9ea87556163b4403ea88d7a4b54e0da6d8e8907306658ed5`。两份最终 native 文件均重新计算 SHA256：baseline `cdfc0093f978a131a608fec65ac15f1526655832a3b571ca7b01e4ba1a53c6b6`，candidate `852dee3bca568063563fc9b66d2f13904b56cc796116fcdd27e5cefe71fa4114`。冻结 Python 包各 56 个 Git 跟踪文件逐字节符合各自 commit。构建记录表明二者使用相同 `release-with-debug` profile、依赖和配置；构建并行度分别为 2、3，不是执行线程配置。移除 debug section 的记录验证全部 28 个 allocated ELF section 未改变。最后检查时生产工作树干净。

独立复核脚本 `independent-performance-check.py` 不导入实现方汇总器，从原始文件重算 120 个主样本的中位数与范围，核对相同 fixture、二进制和 Python source hash、Arrow 25.0.1、各线程上限 4、空 stderr、完整结果摘要、版本、merge 统计、payload hash 与探针事件。各组正好五次，baseline/candidate 交替先后，主测量区间没有重叠。全部 conflict 的 commit hooks 为 `[2,3]`，竞争更新版本为 `[2]`。首次 hook 计时在竞争更新之前；竞争写重写当前已读的 target 行，结合此前实际 factory 重开测试及重试源码，支持发生语义重试。不能只凭两个 commit hooks 作此判断。14 个最终 detector controls 和 20 个独立标记的无探针补测也通过核对。结果保存于 `independent-performance-check.json` 和 `.stdout`，最终运行 stderr 为空。

核心机制证据充分。主测量中所有可优化 candidate 的 replay directory count 都是 0，baseline 都是 1；opaque Scanner 两边都是 1。小输入不落盘时仍能捕获 replay 目录，256 字节 one-shot 正控制也能检测到目录。materialized 和 zero-retry 控制符合预期。这与此前源码及调用栈校准相互支持，能够区分“没进入 replay”与“只没产生 spill 文件”。132 MiB 输入的 baseline 每次生成 132.10–132.11 MiB 的 replay 文件，candidate 每次避免该文件；fallback 保留原行为。该结论强于仅凭 RSS 或计划名称推断缓冲行为。

关键结果如下，均为当前本地、预热缓存、以插入为主的工作负载中位数：

| 场景 | baseline → candidate | 可支持的判断 |
|---|---|---|
| 大 Lance，无冲突 | 230.82 → 218.17 ms；RSS 543.2 → 434.9 MiB | 避免约 132.10 MiB replay 文件；本次延迟和 RSS 较低 |
| 大 Arrow Dataset，无冲突 | 201.76 → 193.26 ms；RSS 747.3 → 631.9 MiB | 避免约 132.11 MiB replay 文件；本次延迟和 RSS 较低 |
| 小 Lance，无冲突，主测量 | 9.28 → 11.93 ms；CPU 13.78 → 13.61 ms | 延迟上升，不能声称小输入提速 |
| 小 Lance，无冲突，无探针补测 | 11.20 → 11.95 ms；CPU 15.89 → 13.86 ms | 延迟差变小但未反转，7/10 配对更慢；不能认定固定 2.65 ms 成本 |
| 大 Lance，有冲突 | 813.29 → 982.04 ms；CPU 685.11 → 732.02 ms；RSS 570.1 → 609.1 MiB | 避免 replay 文件的同时，记录到 CPU +6.8%、RSS 约 +39 MiB 的取舍 |
| 大 Arrow Dataset，有冲突 | 390.78 → 834.62 ms；CPU 649.66 → 648.48 ms | wall 中位数明显升高，但不能据此推断处理成本翻倍 |

小 Lance 无探针补测保留十组交替配对，`LD_PRELOAD` 确实未设置，raw 的 probe hash 为 null。baseline 范围 8.80–14.52 ms，candidate 10.39–13.37 ms。该补测是在观察主测量后进行的单一窄范围诊断，不能替换或混入主样本，也不能证明探针就是差异来源。candidate 增加 factory 调度和重新扫描是源码可见的成本；实验没有分别隔离其贡献。现有数据足以披露小输入可能付出的延迟成本，无需为本候选增加未经验证的大小阈值或新的生产开关。

冲突总 wall time 包含实际执行、竞争更新和随机退避。源码在首轮失败后按约 1.1 倍首轮耗时建立时槽，首次随机选择 0–3 槽；相邻 baseline/candidate 并不共享槽。执行前审计已要求增加首次 hook 与 CPU 记录，最终数据保留了这些字段及全部原始 wall time，没有猜测或扣除等待。大 Arrow conflict 的两边范围分别为 328.71–1195.51 与 375.00–1160.65 ms；CPU 近似不变，而大 Lance 的 CPU 与 RSS 确实升高。小 Arrow conflict 的 CPU 也从 28.91 升至 32.31 ms；小 Lance conflict 虽 wall 中位数下降，CPU 同样升高。因此不能对实际重试宣称通用加速，也不能把全部回退都归咎于随机等待。

六对实际 `analyze_plan` 的归一化拓扑一致，独立核对的 input/output row 和 batch counters 也一致。所有 target build 都为一行一批；小 Lance 来源一批，小 Arrow/Scanner 两批，大来源均 32 批。计划执行前后版本和数据保持不变。这排除了本次捕获计划中的 join 方向或批数差异，但不能证明调度、分配及所有 optimizer estimate 完全相同。两条实现均显示 StreamingTable，计划同名不能替代 detector 证据。opaque Scanner 的大 clean +3.1% 及 conflict wall 波动也保留在正式报告，不能挑掉它们或用它们抹去 eligible 路径的实际成本。

证据边界明确：RSS 是整个进程到 merge 完成的高水位，包括导入与准备；`rchar/wchar` 及 kernel I/O 计数包含目标写入、日志和取消写，不是物理设备流量；五次主重复不足以量化很小变化的稳定效应。无探针补测仅覆盖小 Lance clean。没有冷缓存、远程存储、云环境或更新为主的性能验证。已审读的最终 `performance-report.md` 与 `performance-interpretation.md` 正确保留这些限制及回退，没有用 DEV 耗时作性能结论。

在上述范围内，用户要求的固定 baseline 对比、真实重试、可靠 detector、兼容性、独立审查及发现修复已有本轮证据支持。推荐以“统一适配契约并让可信可重读来源避免 replay”为提交主张，附简短性能取舍。公开名称与 experimental 稳定性、opaque Scanner 需显式能力适配的边界仍是可交给维护者确认的 API 取舍；这些选择已有实现和验证，不是阻塞候选交付的缺失事实。最终性能补充不要求再改生产源码。
