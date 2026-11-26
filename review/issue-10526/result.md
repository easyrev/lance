# 本轮结果

2026-11-26 03:59 UTC，`df` 显示 `/dev/shm` 可用 1,099,804,672 字节（1.02 GiB），低于交接单的 10 GiB 门槛。同次检查 `/` 可用 10,871,189,504 字节（10.12 GiB）。随后复查 `/dev/shm` 可用 37,339,136 字节。计时任务因此结束，两项候选构建均已退出。

| 项目 | 观察 |
|---|---|
| main `make build` | 退出码 0，导入扩展哈希已记录 |
| pure-B `cargo test -q -p lance-encoding --profile release-with-debug` | 退出码 0，2614 个单元测试和 8 个文档测试通过，4 项忽略 |
| pure-B-var `cargo test -q -p lance-encoding --profile release-with-debug` | 退出码 0，2618 个单元测试和 8 个文档测试通过，4 项忽略 |
| pure-B `make build` | 退出码 2，链接器因信号 7（Bus error）退出 |
| pure-B-var `make build` | `rustc` 报 `No space left on device (os error 28)`，两个退出码文件均为 0 字节 |
| 精确性 | main 7 个数据集的全量 scan 和全量随机 take 逐行一致。两个候选均未进入 Python 精确性校验 |
| 计时及 RSS | 阶段 1 共 0 个计时进程。阶段 2 未开始，五项原超标指标没有 final+B 读数 |
| 候选选择及后续代码检查 | 未选择最终提交。最终提交上的 fmt、联合测试及两项 Clippy 未运行 |
| 发布 | 仅有本地执行记录，无推送。现有 #10526 的本地和 origin 分支均为 `d0020f4291a0cb18790ac731df7c24890a169ca1` |

9 份旧 IPC 输入的 SHA256 与上一轮 `linux-64cpu/raw/inputs.sha256` 一致。阶段 1 的数据布局、写法及哈希已记录。

两个候选的编译链接阶段重叠。pure-B 的 `make install` 先执行了一次 editable 扩展构建，之后又执行了规定的 `make build`。第一次安装的文件及其冗余链接副本字节相同，构建期间释放了冗余副本，哈希在 `raw/pure-install-intermediate.txt`。该扩展未用于读取或计时。pure-B-var 的依赖安装使用 `--no-install-project`，随后执行 `make build`。等待任务重启以增加相同扩展文件的哈希核对和缓存空间管理，未进入计时。`scripts/phase2.sh` 与 `scripts/code-checks.sh` 是未执行的准备脚本。
