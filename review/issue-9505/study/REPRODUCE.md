# 复算与复跑入口

## 只读复算

本地安装 Node 后，无需 Lance、ECS 或 workload 执行即可由原始记录复算全部表格与配对比率：

```sh
node scripts/report.cjs .
node scripts/report.cjs . markdown
shasum -a 256 -c SHA256SUMS
```

`results.json` 的每格保留 actual join mode/build、build rows/memory、交换 spill、各输出分区工作量、CPU/pool/RSS/cgroup/TMP/IO；完整指标在 runs 对应文件。配对按 paired-plan 的六个 comparison，先算每 block 比值再取三轮中位数。不要把 stage 与完整 merge、诊断与正式配对、失败与成功混算。

## 原始执行环境与构建

ECS 根为 `/mnt/lance/hypotheses-9505-20261019`。Rust 1.98.1、Cargo 1.98.1；Python validator 为 3.12.3、Lance 14.0.0-beta.19、PyArrow 25.0.1，其真实扩展 SHA 在 fixtures.json。CPU/内存/toolchain 原文在 environment/。

原执行顺序与命令在 scripts/build-probe.sh、diagnostics.sh、pairs.sh、unit-tests.sh。构建的关键命令为：

```sh
source /mnt/lance/env.sh
source /mnt/lance/proxy.sh
proxy-on >/dev/null
cd /mnt/lance/checkouts/hypotheses-9505
export CARGO_TARGET_DIR=/mnt/lance/targets/hypotheses-9505
export CARGO_BUILD_JOBS=6
cargo fmt --all
cargo test -p lance --lib dataset::write::merge_insert::hypotheses --profile release-with-debug --locked --no-run --message-format=json
```

实际编译代码为 snapshot/ 和 full-reconstruction.patch；scripts/hypotheses.rs / deferred_reference.rs 是冻结的移入种子，rustfmt 后编译字节以 snapshot 为准。完整补丁从 U 重建包含 Python/P 外围以及 inherited integration test；新 lib executable 没编译 integration target。check-reconstruction.py 只在新导出目录应用补丁并比对所有原冻结源文件，已通过，不修改实验 checkout。

driver 的唯一入口为 `dataset::write::merge_insert::hypotheses::run_frozen_hypothesis`，由 `LANCE_HYPOTHESIS_SPEC` 指向 spec.json。每格实际 binary 启动命令、cwd、8 GiB/swap=0 cgroup、退出码都记录在 result.json/resource 中。private driver 调用 P 的真实 plan/writer/commit，或清楚标记的 RR/Take 阶段节点；并非 Python 计时模拟。

prepared fixture 复用和新压缩 fixture 生成见 prepare.py，原 reverse source 的补充见 prepare-reverse.py。原始 source values 完全一致，单批/多批的 IPC 容器和 backing 合同不同且各自有 SHA。生成的新文件名/transaction UUID 不要求与其他重建一样；一次新实验必须重新冻结本次文件身份。大型 fixture 和 output IPC 留在 ECS，本地包只保留文件哈希、完整生成器和 oracle。

## 执行与身份检查

原始执行使用 `/mnt/lance/checkouts/U_main/python` 中已经准备好的 uv 环境：

```sh
source /mnt/lance/env.sh
cd /mnt/lance/checkouts/U_main/python
uv run --no-sync python /mnt/lance/hypotheses-9505-20261019/scripts/run.py diagnostics
uv run --no-sync python /mnt/lance/hypotheses-9505-20261019/scripts/run.py pairs /mnt/lance/hypotheses-9505-20261019/paired-plan.json
```

以上是原执行命令，**不要在已有冻结根上重跑**：run_case 使用 mkdir(exist_ok=False)，会拒绝覆盖。要产生新测量，先创建新的运行根，调整新脚本的 ROOT/config/cgroup/计划路径，保持旧输入只读，冻结新的脚本与配置，再执行同合同。不要改写旧 freeze、metrics 或计划来适配新结果。若更换实际源码/编译选项/依赖，必须重新生成二进制身份，不能沿用本轮的 SHA 或统计。

原 sampler 和 fixtures 逻辑执行时从旧 `/mnt/lance/unified-9505-20261019/harness` 只读导入；包内 vendor/previous-harness 是哈希一致的审阅副本。runner 仅在内存中替换 ROOT/command/environment，不改旧文件。各验证 worker 在独立进程和 cgroup 使用固定 U Python 扩展读取结果，不使用待测 binary 自己计算期望值。

现场只读审计命令：

```sh
source /mnt/lance/env.sh
cd /mnt/lance/checkouts/U_main/python
uv run --no-sync python /mnt/lance/hypotheses-9505-20261019/scripts/audit-final.py
```

该脚本会重新核验大输入/阶段输出哈希并写新的审计结果；归档之后应将输出重定向到新记录位置或先复制到新审计根，保留原 audit-final.json。它不重跑 workload 或逐字段 oracle；逐字段断言已由每次执行后的 worker 完成。
