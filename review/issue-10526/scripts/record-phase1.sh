#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
raw=$task/raw
scripts=$(realpath "$(dirname "$0")")
prior=/root/lance/tmp/10526-review/review/issue-10526/linux-64cpu
out=$1
result=$2
template=/root/.agents/skills/issue-branches/assets/README.template.md
mkdir -p "$out/raw" "$out/scripts/reused"
cp "$scripts/handoff.md" "$out/handoff.md"
cp "$scripts/stage0.md" "$out/stage0.md"
cp "$scripts/"*.py "$scripts/"*.sh "$out/scripts/"
cp "$prior/decode-followup/"{common.sh,build-experiment.sh,take.py,verify.py,inspect_data.py} "$out/scripts/reused/"
cp "$prior/"{bench.py,build-shell} "$out/scripts/reused/"
find "$raw" -maxdepth 1 -type f ! -name 'phase2-*' -exec cp -t "$out/raw" -- {} +
python3 "$scripts/datasets.py" "$raw" phase1 > "$out/datasets.md"
python3 "$scripts/summarize.py" report "$raw" > "$out/phase1.md"
cp "$template" "$out/README.md"
{
    echo '# FullZip 共享缓冲解码执行记录'
    echo
    echo "- 阶段 0 的四项判断及代码位置见 [stage0.md](stage0.md)。"
    echo "- 数据集写法、页数、编码、哈希见 [datasets.md](datasets.md)。每批逻辑字节数在 \`raw/write-*.json\`，原始 IPC 哈希在 [raw/inputs.sha256](raw/inputs.sha256)。"
    echo "- 阶段 1 的实测中位数、最小值、最大值与百分比见 [phase1.md](phase1.md)。计时前以 \`verify.py\` 做全量 scan 和全量随机 take，行数见 \`raw/phase1-verify-*.json\`。"
    echo "- 当前执行结果见 [result.md](result.md)。本轮交接单原文见 [handoff.md](handoff.md)。"
    echo
    echo '## 构建'
    echo
    echo '64 个 Lance CPU 线程，release-with-debug。每个构建使用独立的 Cargo target 和 Python 环境。'
    echo
    echo '| 构建 | 提交 | 导入的 Python 扩展 SHA256 |'
    echo '|---|---|---|'
    for variant in base pure var; do
        commit=未记录 hash=未记录
        if [[ -s $raw/commit-$variant.txt ]]; then commit=$(cat "$raw/commit-$variant.txt"); fi
        if [[ -s $raw/extension-$variant.sha256 ]]; then read -r hash _ < "$raw/extension-$variant.sha256"; fi
        printf '| %s | `%s` | `%s` |\n' "$variant" "$commit" "$hash"
    done
    echo
    echo '## 命令与原始结果'
    echo
    echo '- 构建脚本沿用原 `build-experiment.sh` 的 `make build`、profile 和扩展哈希流程，按本轮多个 worktree、虚拟环境、target 和目录结构重写了入口。磁盘门禁和 `uv run` 沿用原 `common.sh` 的方式。原脚本放在 `scripts/reused/`。'
    echo '- `scripts/take.py` 相对原脚本只增加 `--dataset-rows` 并以它取代 `choice(25000, ...)`。扫描的计时从 dataset open 前开始，每次执行 `to_batches(batch_size=1024)`，峰值 RSS 来自 `ru_maxrss`。'
    echo '- 单次计时时序为 base、pure、var，按进程轮转。每个 take 进程使用一个 dataset 句柄和 20 次调用，各进程使用相同的种子和排序行号。'
    echo '- 代码检查退出码及完整日志见 `raw/`。进程输出路径保留运行时的绝对路径。'
} > "$out/README.md"
cp "$result" "$out/result.md"
(cd "$out"; find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS; sha256sum -c --quiet SHA256SUMS)
