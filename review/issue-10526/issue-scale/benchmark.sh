#!/usr/bin/env bash
set -euo pipefail
evidence=$(cd "$(dirname "$0")" && pwd)
repo=$(git rev-parse --show-toplevel)
baseline=$(git rev-parse cb8c25692)
final=$(git rev-parse HEAD)
scratch=$(mktemp -d)
example=rust/lance-file/examples/writer10526.rs
export CARGO_BUILD_JOBS=4
target_root=${BENCH_TARGET_ROOT:-"$repo/target/issue-10526-benchmark"}
export LANCE_CPU_THREADS=8
export RAYON_NUM_THREADS=8
unset LANCE_ENCODING_DICT_DIVISOR LANCE_ENCODING_DICT_MAX_CARDINALITY LANCE_ENCODING_DICT_TOO_SMALL LANCE_ENCODING_DICT_SIZE_RATIO
cleanup() {
    rm -f "$repo/$example" "$scratch/baseline/$example"
    if [ -d "$scratch/baseline" ]; then git worktree remove "$scratch/baseline"; fi
    rm -f "$scratch/writer-base" "$scratch/writer-final"
    rmdir "$scratch"
}
test ! -e "$repo/$example"
trap cleanup EXIT
git worktree add --detach "$scratch/baseline" "$baseline"
printf 'baseline %s\nfinal %s\n' "$baseline" "$final" > "$evidence/benchmark-shas.txt"
build() {
    local label=$1 source=$2 status=0
    local target="$target_root/$label"
    mkdir -p "$source/$(dirname "$example")" "$target"
    cp "$evidence/writer10526.rs" "$source/$example"
    (cd "$source" && CARGO_TARGET_DIR="$target" rtk cargo build -p lance-file --example writer10526 --profile release-with-debug) > "$evidence/build-$label.log" 2>&1 || status=$?
    echo "$status" > "$evidence/build-$label.exit"
    if [ "$status" -ne 0 ]; then return "$status"; fi
    cp "$target/release-with-debug/examples/writer10526" "$scratch/writer-$label"
    rm "$source/$example"
}
build base "$scratch/baseline"
build final "$repo"
printf 'build\ttrial\tversion\tinput_fnv64\tfile_bytes\tpages\tmax_raw_bytes\tmax_encoded_bytes\twrite_s\twrite_cpu_s\twrite_avg_cores\tscan_s\tscan_verify_s\ttake_s\ttake_verify_s\tpage_rows\tencodings\ttake_indices\n' > "$evidence/measurements.tsv"
swap_mib() {
    sysctl -n vm.swapusage | awk '{v=$6+0; if ($6 ~ /G$/) v*=1024; print int(v)}'
}
swap_start=$(swap_mib)
run() {
    local label=$1 trial=$2 status=0 pid pressure swap rss
    local prefix="$evidence/$label-$trial"
    "$scratch/writer-$label" > "$prefix.tsv" 2> "$prefix.log" &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        pressure=$(sysctl -n kern.memorystatus_vm_pressure_level)
        swap=$(swap_mib)
        rss=$(ps -o rss= -p "$pid" || true)
        printf '%s pressure=%s swap_mib=%s rss_kib=%s\n' "$(date +%s)" "$pressure" "$swap" "$rss" >> "$prefix.memory"
        if [ "$pressure" -gt 1 ] || [ "$((swap - swap_start))" -ge 512 ]; then
            printf 'Stopped under memory pressure or swap growth\n' >> "$prefix.log"
            kill -TERM "$pid" 2>/dev/null || true
            break
        fi
        sleep 1
    done
    wait "$pid" || status=$?
    echo "$status" > "$prefix.exit"
    if [ "$status" -ne 0 ]; then return "$status"; fi
    if ! awk -F '\t' -v label="$label" '
        NF != 16 {exit 1}
        label == "base" && ($4 != 1 || $5 != 4500000000) {exit 1}
        label == "final" && ($4 != 135 || $5 > 33554432) {exit 1}
    ' "$prefix.tsv"; then
        echo "Unexpected page metrics ($label $trial)" >&2
        return 1
    fi
    if [ "$trial" != warmup ]; then
        printf '%s\t%s\t' "$label" "$trial" >> "$evidence/measurements.tsv"
        cat "$prefix.tsv" >> "$evidence/measurements.tsv"
    fi
}
run base warmup
run final warmup
for trial in 1 2 3; do
    if [ "$((trial % 2))" -eq 1 ]; then
        run base "$trial"
        run final "$trial"
    else
        run final "$trial"
        run base "$trial"
    fi
done
awk -F '\t' 'NR==2{expected=$4; indices=$18} NR>1 && ($4!=expected || $18!=indices){exit 1} END{if(NR!=7)exit 1}' "$evidence/measurements.tsv"
