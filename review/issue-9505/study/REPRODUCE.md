# 复核与复现入口

本轮工作根为 ECS `lance-ecs:/mnt/lance/unified-9505-20261019`，本地镜像为 `output/unified-9505-20261019`。本地镜像与压缩包保留源码快照、补丁、身份、脚本、完整日志和记录，不包含大 dataset、venv、target 或编译二进制。ECS 上的 fixture、各 cell dataset 和实际扩展仍保留，可重开验证。不要覆盖本轮 root、run、plan 或 freeze；重跑使用新目录和新名称。

## 先复核已有证据

在本地仓库根读取完整配对原值及比率，不导入 Lance：

```sh
node output/unified-9505-20261019/extract-report.cjs --format json
node output/unified-9505-20261019/extract-report.cjs --format markdown
node output/unified-9505-20261019/inspect-plans.mjs output/unified-9505-20261019/diagnostics/*/analyzed-plan.txt
```

正式配对固定为 `pairs-f16-v1`、`pairs-wn-v1`、`pairs-ws-v1`、`pairs-reverse-v1`、`pairs-ordinary-v1`。单独提取某组可加 `--plan pairs-f16-v1`。提取器的 complete 只针对选中的已存在 plan，不代替完整 manifest 审计。

在 ECS 上只读核验实际源码、扩展、build log 与 fixture 的字节身份，并独立复算 records：

```sh
source /mnt/lance/env.sh
cd /mnt/lance/checkouts/U_main/python
uv run --no-sync python /mnt/lance/unified-9505-20261019/audit-results.py \
  --root /mnt/lance/unified-9505-20261019 --verify-files
```

该审计读取 oracle 已保存的断言和字段摘要，不重新扫描每个 cell dataset；真实逐字段扫描已在各次 execute 后由独立 U 进程完成。原始读回命令、cgroup、退出码和资源记录保存在各 cell 的 `validate-resources.json` 或 `validate_unchanged-resources.json`；后者用于失败与诊断。诊断使用 unchanged oracle，不是一次提交成功的证明。

## 从结果追到源代码

1. 先选 `runs/<run_id>/result.json`，核对 `kind`、`status`、`cell`、`contract`、`identity.extension_sha256`，不要凭目录中的 B/P/D 标签认版本。
2. 沿 `plans/<plan>.json` 的 freeze 哈希找到 `freezes/all-v1.json`；核对完整 source hashes、实际 Python module/extension、锁文件、harness hashes 和 build-log hashes。
3. `ports/<variant>/implementation.patch` 应用在共同基线 `0a0d327082988018a25f56147d3b6d02f6c79ecc`。`source/` 是所有修改文件的完整字节快照，`mechanism.json` 与 `port-notes.md` 区分来源和合并调整。U 无补丁。
4. U/D 复用经本轮核验的优化构建，其 freeze 中 build-log 路径仍引用旧证据目录；本包另存与冻结 SHA 完全一致的 [日志副本与路径映射](inputs/reused-build-logs/mapping.json)。实际加载的扩展和本轮测试结果见 `VALIDATION.md`。旧目录的耗时不进入本轮统计。
5. 输入身份在 `fixture-manifests/` 与 plan 内嵌 manifest 中，包括每个文件哈希、spec、元数据和生成器来源。复用 fixture 先核对历史生成器与文件字节；其小型来源文件已按原 SHA 复制到 [inputs/fixture-provenance/](inputs/fixture-provenance/mapping.json)，无需依赖旧本地目录即可检查导入来源。新 fixture 由本轮冻结 `fixtures.py` 生成。

七个 Python 环境的完整依赖列表及采集时间见 `environment/dependencies-supplement-v1/`；D 的全列表是 first-wave 后补采，不能视作其此前全依赖的预先快照。`dependencies-audit.md` 说明版本、lock 和 editable 路径的对应关系。

## 如需重新构建和计时

在新的隔离 checkout 上检出上述共同基线并应用对应补丁，按 checkout 中 `python/AGENTS.md` 先 `make install`，再按 `build-one.sh` 的仓库入口与 `environment/profile.mk` 构建 `release-with-debug --locked`。使用独立 target、venv 与 TMPDIR；不修改 profile 的 LTO。构建完成后才开始计时，两者不得重叠。

将 harness 复制到新的证据目录，按新 checkout/build-log 路径更新新的 config，再执行 `init`、`freeze` 和 fixture 导入/生成。不可仅改旧 freeze 中的路径后沿用其签名。具体 CLI、真实 cgroup v2 控件检查、正确性门槛、资源失败处理、冷读和诊断边界见 [harness/RUNBOOK.md](harness/RUNBOOK.md)。不要直接重跑本目录已完成的 `run-*.sh`：这些脚本使用本轮不可覆盖的 plan 名称，其作用是记录本轮实际调度。

按以下已有脚本核对真实顺序与参数：`run-first-wave.sh` → `run-followup-survival-v1.sh` → `run-pairs-v1.sh` → `run-diagnostics-v1.sh` → `run-audit-final-v1.sh`。每个驱动都有独立日志和退出码。失败及取消队列的旧日志保留，不代表后续重跑自动覆盖了它们。

新一轮须先通过小型语义门槛、相同合同的存活检查，再创建三轮随机配对计划。计时从 execute API 入口开始；source 在 API 内惰性产生，准备成本不会被挪到计时外。资源不足不作为计时值，不能把不同 cache、pool、writer、input form 或源码身份的半轮拼在一起。

## 文件边界

`paired-report.*`、独立审计、技术报告和计划提取 JSON 是派生文件；原始记录为 freeze/plan/fixture manifest、各 run/diagnostic 的 metrics、producer、oracle、资源采样、日志和事件流。逐进程 IO 是累计 API 区间量，新 `.lance` 字节是最终文件量，TMP 是采样同时存活量。完整保留这些差别，不能用某一个数字代替另外两个。

证据包的 `SHA256SUMS` 覆盖包内全部普通文件，清单自身除外；忽略 Python 缓存和 `.DS_Store`。在解包后的本目录运行 `shasum -a 256 -c SHA256SUMS` 可复核打包后字节。这个清单验证归档完整性，不代替上面的源码/二进制/fixture 实验身份审计。原始冻结记录中的 ECS 绝对路径保留原值；移机复现应创建新 freeze。
