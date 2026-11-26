#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'status=$?; echo "$status" > "$raw/measure.exit"' EXIT
space
[[ $(cat "$raw/verify.exit") == 0 ]]
mkdir -p "$raw/p1"
measure() {
    local phase=$1 dataset=$2 rows=$3 op=$4 cohort=$5 trial=$6 variant=$7
    local target="$raw/$phase/$dataset-$op-$cohort-$trial-$variant.jsonl"
    [[ ! -e $target ]]
    local path=$task/$phase/$dataset
    local -a args
    if [[ $op == scan ]]; then
        args=("$tools/scan.py" "$path" "$rows")
    else
        args=("$tools/take.py" "$path" "${op#repeat}" --dataset-rows "$rows" --take-only --repeat 20)
    fi
    run "$variant" "${args[@]}" > "$target.pending"
    mv -- "$target.pending" "$target"
}
run_case() {
    local phase=$1 dataset=$2 rows=$3 op=$4 n=5
    shift 4
    local -a builds=("$@")
    if [[ $op == scan ]]; then n=7; fi
    for cohort in primary repeat; do
        space
        printf '%s %s %s %s %s\n' "$(date -u +%FT%TZ)" "$phase" "$dataset" "$op" "$cohort"
        for ((trial=1; trial<=n; trial++)); do
            for build in "${builds[@]}"; do measure "$phase" "$dataset" "$rows" "$op" "$cohort" "$trial" "$build"; done
        done
    done
}
datasets=(utf8-1page utf8-zstd-25k utf8-zstd-8k binary-zstd-varlen binary-random-varlen binary-zstd-medium binary-medium-default mixed)
row_counts=(25000 25000 8000 12000 12000 99650 99650 16000)
for i in "${!datasets[@]}"; do
    for op in scan repeat128 repeat1024; do
        run_case p1 "${datasets[$i]}" "${row_counts[$i]}" "$op" base head
    done
done
