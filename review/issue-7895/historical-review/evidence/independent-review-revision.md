# 修订审查

首轮发现的 `analyze_plan` 吞错问题已验证关闭。独立探针在最终 DEV 扩展上确认六种来源错误均会传播，正常分析仍成功且不提交数据。此轮未发现新的可确认代码缺陷。定向回归、兼容性和项目 lint 已完成，匹配优化构建的性能比较仍待最终结果。

审查快照为 `review-phase1-final.patch`，SHA256 `9694eb0eaf38d30a9ea87556163b4403ea88d7a4b54e0da6d8e8907306658ed5`，tree `266fe35ffdb06144ba73a255ef8d51e13ba32516`，base 沿用 `4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9`。与首轮 tree 相比，源码差异限于共享 analyze helper 和 Python 回归测试。工作树中临时的 `python/pyproject.toml` 改动不在该固定补丁中，不属于本报告审查的提交内容。

共享 helper 现在检查每个 stream `Result` 并传播错误，不再把失败计划伪装成零行成功报告。配套使用 `LogicalPlan::explain_schema()` 有直接依赖源码依据：DataFusion `AnalyzeExec::create_output_batch` 输出两列字符串，构造函数的 schema 应描述报告，原先传入输入计划 schema 会导致最终报告 batch 构造失败。旧循环同样掩盖了这类错误；只修改循环而不修 schema 会使正常 analyze 回归失败。`root-core-tests.log` 中现有 context 测试已验证缺失扩展时报错、具备扩展时成功。先前出现三项正常 analyze 失败的日志 `review-fix/python-provider.log` 属于中间构建，不能作为最终修复通过证据。

新 Python 错误矩阵涵盖 replayable/streaming × execute/analyze_plan × factory/metadata/batch，并验证数据和版本没有被提交修改。它与首轮独立复现直接对应。新增竞争 upsert 在同一提交中重写旧行并插入新匹配键；最终行集及插入/更新统计能验证第二轮重新判断匹配关系。仅观察 commit hook 次数不能达到这一目的，因此不采用纯 append 夹具的结果是合理的。这里依据测试源码判断断言能力，最终是否通过仍取决于新扩展的运行结果。

Phase 1 来源记录已获允许后读取。`phase1-comparison.md` 将对照前快照、读取时点、材料来源和唯一新增冲突测试分开记录；本审查未把旧阶段测试记录当作本轮结果，也未读取排除的旧 PR 或派生实现。核心修复来源仍是首轮独立错误复现。

独立修订探针 `independent-review-revision-probe.py` 已在新扩展 SHA256 `b4b1c1da690158d29e53ee79e8a57138b934054d16961c8e6ec25f63db4280d4` 上运行。脚本强制核对该 hash，原始结果保存在 `independent-review-revision-probe.json`，对应 stderr 为空。环境为 Python 3.12、Arrow 25.0.1、单 Tokio worker。

replayable 的 factory、schema、batch 三种错误均返回 `OSError`。streaming 的 factory/schema 错误在 Python 层返回 `ValueError`，batch 错误返回 `OSError`。错误路径保持初始数据及版本。materialized、streaming、replayable 三种来源的正常 merge 分析都返回 `num_updated_rows=1`，dataset 版本保持 1；普通 scanner 分析也成功。这些结果关闭首轮 P2，并确认修复没有保留中间构建的正常报告失败。

独立运行命令：在 `/workspace/lance-7895/python` 加载 `source /workspace/issue-7895-evidence/env.sh`，执行 `TOKIO_WORKER_THREADS=1 REVIEW_EXPECTED_EXTENSION_SHA256=b4b1c1da690158d29e53ee79e8a57138b934054d16961c8e6ec25f63db4280d4 uv run --no-sync python /workspace/issue-7895-evidence/independent-review-revision-probe.py`。首轮失败记录未覆盖。

已读取 `root-workspace-clippy.log` 的完整检查完成记录，以及 `root-core-tests.log` 的共享 helper context 测试通过记录。补读 `review-final` 的原始日志确认：Python 定向 106 项、写入/MemWAL 回归 137 项、source doctest 1 项、Rust provider 4 项通过，完整 Python lint 和 binding clippy 完成。当前 Arrow、最低支持 Arrow 14.0.2、单 worker 兼容性结果均指向上述新扩展 hash，包含真实冲突后的两次 factory 调用。尚未完成的匹配性能测量继续保留为交付证据缺口。
