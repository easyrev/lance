# ECS benchmark 环境交接

2026-10-18：环境已恢复并通过小型校验，尚未执行 benchmark。

## 连接与环境

- 实例：`i-uf65tdngzapumyvnp7yk`，`root@8.153.87.56`；上海，i4r，16 vCPU / 128 GiB，Ubuntu 24.04。
- 本地盘：894 GiB NVMe，ext4，挂载 `/mnt/lance`，已配置开机挂载。
- 工具链：Rust 1.98.1、Python 3.12.3、uv 0.13.1；构建使用 `release-with-debug`。
- 本机 SSH 入口：`/Users/salamanca/workspace/personal/Lance/output/ecs-restore-20261018/ssh-ecs`。

在远端 shell 中加载一次：

```sh
source /mnt/lance/env.sh
source /mnt/lance/proxy.sh
proxy-on
```

## 目录与版本

- 工作树：`/mnt/lance/checkouts/{U,B,C,P}`；各变体使用独立的 `/mnt/lance/targets/<variant>`。
- 任务文档：`/mnt/lance/validation-9505/{codex-ecs-validation.md,lance-9505-unified-design.md}`，与用户原文件一致。
- 当前交接：`/mnt/lance/RESTORED-ENVIRONMENT.md`；历史 `RUNBOOK.md` 中的主机与构建状态已过时。

| 变体 | 冻结 revision | 状态 |
| --- | --- | --- |
| U | `dc53d5d174af62c49ddd98d1024a64488c1e4404` | 已构建并恢复 |
| B | `793e4e27119540a17ae37ce78d4f5f4d52060a93` | 未构建 |
| C | 同 U | 待实现 |
| P_reconstructed | `90d981870c960e3bb55bfa46b206853ea4282fdb` | 已构建并恢复 |

P 与任务书中缺失的历史 P 是否同树尚未证明，结果中使用 `P_reconstructed` 标签。本轮先按冻结基线比较，不更新 main 替换对照。

## 执行注意

- 先读两份任务文档及对应 checkout 的 AGENTS；任务包含实现 C、测试、runner 和分阶段测量。
- 只运行已恢复的 U/P 时使用 `uv run --no-sync`；重新 `uv sync` 可能使 PyO3 缓存失效。修改源码、依赖或新建工作树时遵守仓库构建流程，不并发写同一 target。
- U/P 导入与读写、P 两项测试、原构建输入的缓存复用已通过；这不代表性能 gate 通过。详细记录在 `/mnt/lance/restore-verification/`。
- Codex CLI 0.163.0 已安装并登录，模型最小调用返回 `READY`；tmux 断开 SSH、继续运行及重新接入已验证。新机资源边界仍按 Gate 0 核验。
