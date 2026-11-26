#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
prior=/root/lance/tmp/10526-review/review/issue-10526/linux-64cpu
scripts=$(realpath "$(dirname "$0")")
raw=$task/raw
export LANCE_CPU_THREADS=64
unset LANCE_FILE_WRITER_MAX_PAGE_BYTES
trap 'status=$?; echo "$status" > "$raw/phase1.exit"' EXIT
df -h / /dev/shm | tee -a "$raw/space.log"
for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
for status in phase1-data build-base build-pure build-var test-var verify-base; do [[ $(cat "$raw/$status.exit") == 0 ]]; done
run() (
    local variant=$1 checkout
    shift
    case $variant in
        base) checkout=/root/lance/base ;;
        pure) checkout=/root/lance/shared-buffer-pure ;;
        var) checkout=$task/checkout-var ;;
    esac
    cd "$checkout/python"
    if [[ $variant == base ]]; then
        export UV_PROJECT_ENVIRONMENT=$checkout/python/.venv
    else
        export UV_PROJECT_ENVIRONMENT=$task/venv-$variant
    fi
    exec uv run --frozen --no-sync python -B "$@"
)
sets=(utf8-1page utf8-zstd-25k utf8-zstd-8k binary-zstd-varlen binary-random-varlen binary-zstd-medium mixed)
row_counts=(25000 25000 8000 12000 12000 99650 16000)
inputs=(/dev/shm/lance-10526/ipc/wide-unique.arrow /dev/shm/lance-10526/ipc/wide-unique.arrow /dev/shm/lance-10526/ipc/wide-unique-8k.arrow)
for dataset in "${sets[@]:3}"; do inputs+=("$task/ipc/$dataset.arrow"); done
variants=(base pure var)
for i in "${!sets[@]}"; do
    dataset=${sets[$i]}
    for variant in "${variants[@]}"; do
        if [[ $variant == base ]]; then continue; fi
        echo "verify $dataset $variant"
        run "$variant" "$prior/decode-followup/verify.py" "$task/data/$dataset" "${inputs[$i]}" > "$raw/phase1-verify-$dataset-$variant.json"
    done
done
measure() {
    local operation=$1 dataset=$2 rows=$3 trial=$4 variant=$5
    local -a args=("$scripts/scan.py" "$task/data/$dataset" "$rows")
    if [[ $operation != scan ]]; then
        args=("$scripts/take.py" "$task/data/$dataset" "${operation#take}" --dataset-rows "$rows" --take-only --repeat 20)
    fi
    echo "$operation $dataset $trial $variant"
    run "$variant" "${args[@]}" > "$raw/phase1-$operation-$dataset-$trial-$variant.jsonl"
}
for i in "${!sets[@]}"; do
    dataset=${sets[$i]}
    operations=(scan take128 take1024)
    if [[ $dataset == utf8-zstd-8k ]]; then operations=(scan take128); fi
    for operation in "${operations[@]}"; do
        for trial in 1 2 3; do
            for variant in "${variants[@]}"; do
                measure "$operation" "$dataset" "${row_counts[$i]}" "$trial" "$variant"
            done
        done
        if python3 "$scripts/summarize.py" stop "$raw" "$operation" "$dataset"; then
            echo "pure-B regression"
            exit 3
        fi
        if python3 "$scripts/summarize.py" retry "$raw" "$operation" "$dataset"; then
            for trial in 4 5; do
                for variant in "${variants[@]}"; do
                    measure "$operation" "$dataset" "${row_counts[$i]}" "$trial" "$variant"
                done
            done
        fi
        if python3 "$scripts/summarize.py" stop "$raw" "$operation" "$dataset"; then
            echo "pure-B regression"
            exit 3
        fi
    done
done
