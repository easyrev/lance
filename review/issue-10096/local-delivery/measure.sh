#!/usr/bin/env bash
set -euo pipefail
export LANCE_WORKTREE=issue10096
result=/mnt/lance/results/issue10096/measurement
mkdir -p "$result"
exec > >(tee "$result/session.log") 2>&1
trap 'code=$?; printf "%s\n" "$code" > "$result/exit.code"' EXIT
exec 9>/mnt/lance/locks/worktree-$LANCE_WORKTREE.lock
flock -x 9
exec 8>/mnt/lance/locks/heavy.lock
flock -x 8
source /mnt/lance/tools/env.sh
ps -eo pid,ppid,pcpu,pmem,comm,args --sort=-pcpu > "$result/processes-before.txt"
if ps -eo comm | grep -Eq '^(cargo|rustc|pytest|maturin)$'; then
    echo 'Another build or test is active. Measurement did not start.' >&2
    exit 3
fi
baseline=/mnt/lance/results/issue10096/baseline-build-verified/bench
fixed=/mnt/lance/results/issue10096/fixed-build/bench
sha256sum "$baseline" "$fixed" > "$result/binaries.sha256"
{ date -u --iso-8601=seconds; uname -a; lscpu; free -h; df -h /mnt/lance; } > "$result/host.txt"
cp /mnt/lance/state/issue10096/{revision,working.diff,verified} "$result/"
cp /mnt/lance/results/issue10096-measure.sh "$result/command.sh"
# Create one fixture. Both publication variants receive byte-identical copies.
"$baseline" prepare "$result/fixture.lance" "$result/staged.pb" 4000000 > "$result/prepare.jsonl"
cp -a "$result/fixture.lance" "$result/baseline.lance"
cp -a "$result/fixture.lance" "$result/fixed.lance"
diff -qr "$result/fixture.lance" "$result/baseline.lance" > "$result/baseline-copy.diff"
diff -qr "$result/fixture.lance" "$result/fixed.lance" > "$result/fixed-copy.diff"
tar -czf "$result/fixture.tar.gz" -C "$result" fixture.lance staged.pb
"$baseline" publish "$result/baseline.lance" "$result/staged.pb" > "$result/baseline-publish.jsonl"
"$fixed" publish "$result/fixed.lance" "$result/staged.pb" > "$result/fixed-publish.jsonl"
tar --exclude='*/data/*' --exclude='*/_indices/*' -czf "$result/publication-metadata.tar.gz" \
    -C "$result" baseline.lance fixed.lance
# Every query invocation warms OS pages with the same index-disabled full scan.
# Fresh-session opens a new Lance session per query. Warm-session reuses one.
# Discard five warmup queries per invocation. Retain 20 measurements.
for round in 1 2 3 4 5; do
    for cache in fresh-session warm-session; do
        if (( round % 2 )); then
            order=(baseline fixed)
        else
            order=(fixed baseline)
        fi
        for label in "${order[@]}"; do
            binary=$baseline
            [[ $label != fixed ]] || binary=$fixed
            "$binary" query "$result/$label.lance" "$label" "$cache" 20 \
                > "$result/$round-$cache-$label.jsonl" \
                2> "$result/$round-$cache-$label.plan.txt"
        done
    done
done
ps -eo pid,ppid,pcpu,pmem,comm,args --sort=-pcpu > "$result/processes-after.txt"
date -u --iso-8601=seconds > "$result/finished-at.txt"
