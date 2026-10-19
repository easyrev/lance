# 最终证据一致性复核

本复核在全部结果同步后完成，仅使用本地 Node 标准库读取记录、重算摘要和校验文件哈希，没有 SSH、重新构建、导入 Lance、执行 workload 或重新扫描 dataset。未发现阻断本轮报告的记录一致性问题。最终状态以 [README](README.md)、[REPORT](REPORT.md) 和 [audit-final-v1.json](audit-final-v1.json) 为准；[final-pairs-audit.md](final-pairs-audit.md) 与更早审查保留其当时范围和待办措辞，不回写历史。

## 计划、执行与独立 oracle

从 16 份 plan 的全部 run_id 出发，逐项与目录、result、events、gate 和最终 summary 对照，得到以下精确集合；没有缺格、重复、孤儿记录或历史失败 reference。

| 计划类型 | 实际格数 | 结果 |
| --- | ---: | --- |
| correctness | 28 | 28 validated_success |
| survival | 44 | 36 validated_success、7 resource_exhausted、1 confirmed_oom |
| cold | 2 | 2 validated_success |
| pairs | 87 | 87 validated_success |
| diagnose | 23 | 23 validated_diagnostic |
| 合计 | 184 | 161 execute + 23 diagnostic；execute 为 153 成功、7 资源不足、1 OOM |

本地独立检查完成 14,001 项断言，错误为零。检查覆盖每格完整 cell/spec/initial snapshot、fixture manifest、重建 contract、实际加载扩展身份、pool 描述与配置、metrics/result 一致性、producer 原始记录与聚合、独立 U validator 身份、完整字段清单、行数/动作数/版本、执行与验证资源、事件及 gate。184 份 oracle 的字段清单合计为 2,881 列次；368 个执行/验证 cgroup 路径互不重复，均记录独立空组起点、8 GiB memory.max、swap 0 和 OOM-group 设置。23 份 analyzed-plan.txt 的 SHA 均与其 metrics 相符。

8 次失败全部有独立 unchanged oracle：F16 U 为 cgroup OOM；F16/Wn/Ws CTX、Ws B、F64 D、R_admission P/DP 为资源不足。失败组重新打开 latest snapshot，验证原版本及全用户字段未变。OOM 依据执行组的 oom_kill 增量，未将退出码或 validator 的状态替代 OOM 证据；F16 U 的同一组多进程被杀也没有计成多个独立失败。失败和诊断均未进入配对时间样本。

正式配对的 30 项预登记比较、90 个同 block 比值，已直接用原始 execute 时间重新相除、排序并取三值中位数，与 audit、summary 一致。全部 87 次执行和慢样本保留。更细的逐值、CPU、RSS、IO 与 TMP 检查见 [final-pairs-audit.md](final-pairs-audit.md)；本次没有用独立候选中位数的商替代配对统计。

## 最终现场审计与身份

[run-audit-final-v1.sh](run-audit-final-v1.sh) 明确执行 `audit-results.py --verify-files`。最终审计 JSON 记录 `audit_status=passed`、`live_file_verification_requested=true`、`planned_live_files_verified=true`，errors/warnings 均为空。first-wave、followup-survival、pairs、diagnostics、audit 五份驱动退出记录均为 0；最终审计日志结束时间为 `2026-10-18T23:06:34+00:00`。

| 文件 | 本次实际 SHA-256 |
| --- | --- |
| audit-final-v1.json | `0d72c51063ddcd96cb6642e419f866d11a09d3ef119e8db1389d8875111a7048` |
| audit-results.py | `ab38e03be73fdbf369733823329d53053753915d17a3326adfa6451bfa972f86` |
| freezes/all-v1.json | `19a95b34dc937a4c8ebbe254e28361b6eedbb9e1c2eeb18f28c2919c704126ae` |
| freezes/fixtures.json | `9280b301f0c831cfd12b85170763716d80b62b3e651f5e392f2ebaa698d7911e` |

审计脚本的现场分支实际核验 checkout 源文件、加载的 extension、build log、fixture 全文件集合及内容，并检查导入 fixture 的旧 freeze/manifest/generator 来源。上述成功是 ECS 上运行留下的记录；本次本地复核没有再次访问 ECS，也不能在不含二进制和 datasets 的镜像中重新证明这些远端字节。脚本自身哈希与最终审计记录一致，两个 freeze 引用的四份 harness 文件也逐字匹配。六个 port 的 24 份修改源码快照均与相应冻结 source_hashes 相等。

## 打包修正与可移植性

- U/D 旧 build log 的包内副本已与 all-v1 冻结 SHA 逐字核对，见 [路径映射](inputs/reused-build-logs/mapping.json)。这保留旧构建时间与来源，不把复用构建伪装成新构建。
- 两个旧 fixture root 的 freeze.json、fixture-hashes.json、fixtures.py 共六份小文件已原样复制，见 [fixture 来源映射](inputs/fixture-provenance/mapping.json)。每份 SHA 与 import origin 相等；对应十个导入 fixture 的完整文件映射和 spec 也与旧 manifest/freeze 相等。没有复制或修改 datasets。
- cost-mechanism 原先引用的原设计和 DF registry 文件在当前机器上均存在；问题是离开该绝对路径后的可移植性。现已改为包内原设计、ports 与 [dependency-excerpts](dependency-excerpts/README.md) 相对链接。原设计副本与原路径 SHA 相同。DF 三份片段保留版本、原行号、完整原文件 SHA 和片段 SHA；Lance Take 片段从固定基线 Git 对象提取，完整 SHA 与 frozen U 相等。DF 片段来源是本机 registry 54.1.0，不能额外宣称远端依赖源码已逐文件校验。
- README、REPORT、REPRODUCE、VALIDATION、cost-mechanism 与新增片段中的本地 Markdown 链接已检查可解析。REPRODUCE 同时列出 validate 与 validate_unchanged 的资源文件名。

这些是分析附录和来源副本，未修改冻结 harness/auditor、历史审计、原始 run/diagnostic、plan、freeze 或测量结果。归档生成和压缩包解压复核由主任务完成，不属于本次已验证范围。

## 结论中必须保留的边界

`validated_diagnostic` 的含义仍须单独说明：基线 analyze helper 消费 stream 时丢弃 `Err`，因此它证明 API 返回、producer 完整 yield 记录、身份匹配和 unchanged oracle，不证明底层执行无隐藏错误地完整结束。完整 producer 记录也不是 EOF poll 或下游 retention 证明。真实 execute 加独立完整字段 oracle 才是本轮完成与性能的主要证据；audit 的 warnings 空列表不消除这一解释限制。

资源口径同样不变：configured pool 不是 RSS 上限，U 实际 execute pool 无界；sampled RSS 为采样到的单进程最大值，cgroup peak 包含该组被计费的缓存，hardlink 共享页的 charge 不一定归本组。process rchar/syscr 不等于物理读量、Take 次数或对象存储请求；TMP 是采样存活文件量，不能替代累计 IO 或最终新 `.lance` 字节。两次 cold 仍只是 fadvise 尝试、mincore 顺序快照及实际 read_bytes 支持的单格观测，没有三轮 cold 结论。

本轮没有通用默认策略胜者：N_dense 的 late 回退、V_dense 中 D/DB 的 CPU 成本、P/DP reverse 容量失败、D 的 F64 key/address/hash 增长仍保留。已有 indexed/Columns、全工作区 CI、远端对象存储、高覆盖率策略选择器及严格 reservation 上限不在这份完成证明之内。失败 unchanged oracle 证明当前最新版本和值未改变，不证明没有 orphan 文件或每个历史 manifest 都已审查。D 完整依赖列表为首波后补采，也不能回填为先前完整冻结。
