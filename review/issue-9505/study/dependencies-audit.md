# Python 依赖记录审计

七个环境 U、B、P、D、CTX、DB、DP 的补充依赖列表在仅归一化 Lance editable checkout 路径后完全相同。每份列表包含 72 个 `name==version` 条目及 1 个 editable Lance 条目，未发现包缺失、额外包或版本差异。U、B、P、CTX、DB、DP 的补采列表还与各自较早的完整列表逐字节相同。**D 的首份完整列表在第一波结束后补采，不能据此声称 D 在第一波前已完整冻结依赖。**

本审计只读取本地同步的证据并用 Node.js 比较内容，没有 SSH、导入 Lance、运行 Python、执行 benchmark 或运行 `audit-results.py`；没有修改冻结 harness 或测量记录。

补采入口 [capture-dependencies.sh](capture-dependencies.sh) 对每个明确指定的 checkout 执行 `uv pip freeze --python .venv/bin/python`，并通过 `uv run --no-sync python` 记录核心包的 distribution metadata。补采开始时间为 **2026-10-18 22:14:37 UTC / 2026-10-19 06:14:37 UTC+8**，来自 [captured-at.txt](environment/dependencies-supplement-v1/captured-at.txt)。这是顺序采集的开始时间，不是七环境的同时快照，也没有逐环境结束时间。

[first-wave.log](logs/first-wave.log) 的最后时间为 2026-10-18 22:14:22 UTC，[first-wave-exit-code](logs/first-wave-exit-code) 为 0。[run-followup-survival-v1.sh](run-followup-survival-v1.sh) 先要求第一波退出码为 0，再调用补采入口，随后才运行第二阶段 survival/cold。上述记录与“第一波之后、第二阶段之前补采”一致。

| 环境 | Editable checkout（归一化前） | 较早完整列表 | 与补采原始文本比较 |
|---|---|---|---|
| U | `/mnt/lance/checkouts/U_main/python` | [environment/U-dependencies.txt](environment/U-dependencies.txt) | 完全相同 |
| B | `/mnt/lance/checkouts/unified-9505-B/python` | [logs/B-dependencies.txt](logs/B-dependencies.txt) | 完全相同 |
| P | `/mnt/lance/checkouts/unified-9505-P/python` | [logs/P-dependencies.txt](logs/P-dependencies.txt) | 完全相同 |
| D | `/mnt/lance/checkouts/K_check/python` | 本轮及已检查的旧 killer-merge 证据中未找到 | 无法追溯比较 |
| CTX | `/mnt/lance/checkouts/unified-9505-CTX/python` | [logs/CTX-dependencies.txt](logs/CTX-dependencies.txt) | 完全相同 |
| DB | `/mnt/lance/checkouts/unified-9505-DB/python` | [logs/DB-dependencies.txt](logs/DB-dependencies.txt) | 完全相同 |
| DP | `/mnt/lance/checkouts/unified-9505-DP/python` | [logs/DP-dependencies.txt](logs/DP-dependencies.txt) | 完全相同 |

U 的较早环境采集开始时间为 2026-10-18 20:03:58 UTC，见 [environment/captured-at.txt](environment/captured-at.txt)。另外五份较早列表由 [build-one.sh](build-one.sh) 在安装、优化扩展构建及 binary identity 记录之后生成；这些列表自身没有嵌入采集时间。本次比较未将它们重新标记为补采时生成。

归一化只将每份列表中唯一的 `-e file:///mnt/lance/checkouts/<对应 checkout>/python` 行替换成 `-e file:///<LANCE_CHECKOUT>/python`，保留其他条目、顺序与版本，使用 LF 并保留一个结尾换行。七份归一化内容的共同 SHA-256 为：

```text
e080637414e3e123ad0e711a6a601a0b7c72ed23a0cc86cca9456292f42fe999
```

[SHA256SUMS](environment/dependencies-supplement-v1/SHA256SUMS) 中的 15 个条目（七份列表、七份 core JSON、一个采集时间文件）均与本地同步文件的实际 SHA-256 匹配。七份 core JSON 逐字节相同，其共同 SHA-256 为 `077a029c6d84db71a4447f223abab124edc1c8e04a31300755f418bb15e7aa35`，记录的 Python 为 3.12.3，NumPy 为 2.5.1，PyArrow 为 25.0.1，pylance distribution version 为 14.0.0b19。完整列表中的 NumPy、PyArrow 版本与 core JSON 一致；七环境的 Python、PyArrow 与 [all-v1 freeze](freezes/all-v1.json) 的实际导入记录一致。Lance 导入版本写作 `14.0.0-beta.19`，distribution metadata 写作 `14.0.0b19`；性能候选的区分仍依据冻结的源文件与实际 `.so` SHA，不依据这个共同版本字符串。

all-v1 中七候选的 `Cargo.lock`、`python/Cargo.lock`、`python/uv.lock` 分别相同。补采的包名和版本相同不代表所有第三方 wheel、动态库或环境文件逐字节相同；完整依赖列表没有这些文件的内容 hash。D 在第一波中已有实际 Lance module/extension 路径、`.so` SHA、Python/PyArrow 版本和源文件 hash 证据，但这些证据不能替代缺失的当时完整 pip 列表。

因此，本次证据支持：补采时七环境的已安装 Python distribution 列表一致；有早期列表的六环境未观察到版本列表变化；D 的完整依赖一致性是事后补充证据。后续配对可以引用这份补采记录及其时间，但不能把它回填成第一波运行前的完整依赖冻结。
