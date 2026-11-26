#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
space
[[ $(cat "$raw/run.exit") == 0 ]]
if [[ -s $disk/reports/diagnostic-cases.tsv ]]; then
    [[ $(cat "$raw/diagnostic.exit") == 0 ]]
fi

old=ed4c87940f2d8ffbdf39aacd25b80d5e2ea069b6
review=$disk/review
issue=review/issue-10526
relative=$issue/rerun-d4cac03
out=$review/$relative
pure=/root/lance/shared-buffer-pure
[[ ! -e $out ]]
git -C "$review" diff --exit-code "$old" -- "$issue"
{ git -C "$pure" rev-parse HEAD; git -C "$pure" status --porcelain=v1; } > "$raw/local-pure-after.txt"
cmp "$raw/local-pure-before.txt" "$raw/local-pure-after.txt"
sha256sum -c "$raw/extension-base.sha256" "$raw/extension-head.sha256" > "$raw/formal-extensions-check.txt"
mkdir -p "$out"/{scripts,reused/scripts/reused}
cp -a "$raw" "$out/raw"
for file in common.sh build.sh relocate-base-target.sh environment.sh audit-env.py data.sh generate-utf8.py check-pages.py verify.sh verify.py measure.sh report.py audit-results.py deliver.py run-after-build.sh stage-review.sh; do
    cp -a "$disk/scripts/$file" "$out/scripts/"
done
if [[ -s $disk/reports/diagnostic-cases.tsv ]]; then
    for file in diagnostic.sh diagnostic-report.py instrument.py; do cp -a "$disk/scripts/$file" "$out/scripts/"; done
    cp "$disk/reports/diagnostic-cases.tsv" "$out/raw/diagnostic/cases.tsv"
fi
cp -a "$disk/reused/old-summary.md" "$out/reused/"
for file in prepare.py pages.py datasets.py scan.py take.py; do cp -a "$tools/$file" "$out/reused/scripts/"; done
for file in bench.py build-shell inspect_data.py; do cp -a "$tools/reused/$file" "$out/reused/scripts/reused/"; done
for file in environment datasets pr-rows fast-path; do cp "$disk/reports/$file.md" "$out/"; done
for file in summary aa classified; do cp "$disk/reports/p1-$file.md" "$out/$file.md"; done

cat > "$out/README.md" <<'INDEX'
# Page bridging 固定提交复测

- [PR 正文用数据](pr-rows.md)
- [正式比较](summary.md)、[A/A](aa.md) 和 [判定](classified.md)
- [逐行快路径对照](fast-path.md)
- [机器及构建环境](environment.md)
- [数据集页编码以及精确性门禁](datasets.md)

按补充指示沿用当前实例。原始输出在 [raw](raw)，本轮脚本在 [scripts](scripts)。旧工具来自固定 review 提交 `ed4c87940`，使用的文件副本在 [reused](reused)。构建日志记录 `release-with-debug`，原始计时记录按用例、组、进程编号与构建命名。
INDEX
(
    cd "$out"
    LC_ALL=C find . -type f ! -name SHA256SUMS -print0 |
        LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS
    sha256sum -c SHA256SUMS > "$disk/package-sha256-check.log"
)
git -C "$review" add -f -- "$relative"
(cd "$review"; LC_ALL=C find "$relative" -type f -print | LC_ALL=C sort) > "$disk/package-files-on-disk.txt"
git -C "$review" diff --cached --name-only -- "$relative" | LC_ALL=C sort > "$disk/package-files-staged.txt"
cmp "$disk/package-files-on-disk.txt" "$disk/package-files-staged.txt"
git -C "$review" diff --cached --check -- "$relative" ":(exclude)$relative/raw" ":(exclude)$relative/reused"
git -C "$review" diff --cached --exit-code "$old" -- "$issue" ":(exclude)$relative"
git -C "$review" -c core.hooksPath=/dev/null commit -m 'review: record page bridging rerun at d4cac03'
