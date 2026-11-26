# #10526 第三列的匹配环境复测

比较 base `cb8c25692` 读取 base 文件、final `d0020f429` 和 final+B `ed0a18841` 读取同一份 final 文件。扩展均复用现有构建，未重新编译，所有读测使用 `LANCE_CPU_THREADS=64`。[导入 RSS 与扩展 SHA256](environment.md)

9 类数据共 18 份 .lance 文件，与旧版第三列证据中的 SHA256 一致。两份 final 文件复用上轮现存文件，其余以原命令重建。每个数据集运行 scan 和单次 take(128)。wide-unique 额外运行重复 take(128) 和 take(1024)，每个进程各读 20 次。scan 每构建每组 7 个进程，take 每构建每组 5 个。各用例先运行正式组，再在原环境和原构建中运行等样本量重复组，两组均按构建轮转。20 个用例，共 708 个独立计时进程。

- [三列中位数、区间、百分比和判定](summary.md)
- [每构建和每指标的 A/A 差](aa.md)
- [超出噪声的指标及计数](classified.md)
- [样本审计](audit.txt)与[计时原始输出](timed-processes.tar.gz)

每项比较采用双方各自 A/A 中位数绝对差的较大值作为该比较的噪声参照。仅在中位数绝对差严格超过该值两倍且两组 min–max 不相交时，按方向记为收益或回归。判定使用未舍入数据。

安装核对首次发现四套环境的 wheel RECORD 中含各自路径相关的命令启动器哈希。计时启动前确认这些元数据差异的文件实际哈希及启动器内容，仅本地路径不同，其余 site-packages 字节一致。四份 pip freeze 逐字节相同。首次门槛检查未产生计时样本。环境记录、数据哈希和命令见 [环境与脚本](environment-and-scripts.tar.gz)。原始输出压缩归档并解压逐字节核验。[交接单](handoff.md)

| 比较 | 收益 | 回归 | 在噪声内 |
|---|---:|---:|---:|
| base → final | 7 | 29 | 14 |
| base → final+B | 19 | 12 | 19 |
| final → final+B | 29 | 0 | 21 |

原来关注的五项峰值 RSS 取同一批正式样本。以下判定按本轮 A/A 规则。

| 项目 | base → final | base → final+B | base → final+B 判定 |
|---|---:|---:|---|
| wide-unique-8k scan | +29.53% | −0.93% | 在噪声内 |
| wide-repeated scan | +24.20% | +23.79% | 回归 |
| wide-repeated take | +14.99% | +14.73% | 回归 |
| wide-clustered scan | +12.72% | +9.95% | 回归 |
| wide-clustered take | +15.67% | +15.84% | 回归 |
