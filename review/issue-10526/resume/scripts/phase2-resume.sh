#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
prior=/root/lance/tmp/10526-review/review/issue-10526/linux-64cpu
scripts=$(realpath "$(dirname "$0")")
raw=$task/raw
disk=/root/lance/tmp/shared-buffer-build
old=/dev/shm/lance-10526/ipc
export LANCE_CPU_THREADS=64 TMPDIR=$disk/tmp UV_CACHE_DIR=/root/lance/cache/uv
unset LANCE_FILE_WRITER_MAX_PAGE_BYTES
trap 'status=$?; echo "$status" > "$raw/phase2.exit"' EXIT
space() {
    df -h / /dev/shm | tee -a "$raw/space.log"
    for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
}
space
[[ $(cat "$raw/phase1.exit") == 0 ]]
[[ $(cat "$disk/previous-build-records/build-base.exit") == 0 ]]
[[ $(cat "$disk/raw/build-final-b.exit") == 0 ]]
[[ $(git -C /root/lance/final rev-parse HEAD) == d0020f4291a0cb18790ac731df7c24890a169ca1 ]]
sha256sum -c "$prior/decode-followup/raw/extension-final.sha256"
printf "Phase 2 estimate: 12,172,885,724 bytes of Lance files for base + final.\n" >> "$raw/space.log"
datasets=(wide-unique wide-unique-8k wide-low-card wide-repeated wide-template wide-clustered wide-mixed wide-constant narrow)
variants=(base final final-b)
run() (
    local variant=$1 checkout
    shift
    case $variant in
        base|final) checkout=/root/lance/$variant ;;
        final-b) checkout=/root/lance/shared-buffer-final ;;
    esac
    cd "$checkout/python"
    if [[ $variant == final-b ]]; then
        export UV_PROJECT_ENVIRONMENT=$disk/venv-final-b
    else
        export UV_PROJECT_ENVIRONMENT=$checkout/python/.venv
    fi
    export LANCE_BENCH_PROTO_DIR=$checkout/protos
    exec uv run --frozen --no-sync python -B "$@"
)
mkdir -p "$task/phase2"
measure() {
    local dataset=$1 operation=$2 trial=$3 variant=$4 source=$4
    if [[ $variant == final-b ]]; then source=final; fi
    local path=$task/phase2/$dataset/$source
    echo "$dataset $operation $trial $variant"
    if [[ $operation == repeat* ]]; then
        run "$variant" "$scripts/take.py" "$path" "${operation#repeat}" --dataset-rows 25000 --take-only --repeat 20 > "$raw/phase2-$operation-$dataset-$trial-$variant.jsonl"
    else
        run "$variant" "$prior/bench.py" read "$path" "$old/$dataset.arrow" "$operation" > "$raw/phase2-$operation-$dataset-$trial-$variant.jsonl"
    fi
}
for dataset in "${datasets[@]}"; do
    space
    pair=$task/phase2/$dataset
    mkdir -p "$pair"
    for variant in base final; do
        run "$variant" "$prior/bench.py" measure "$old/$dataset.arrow" "$pair" --writers 1 --file-stats --keep "$pair/$variant" > "$raw/phase2-write-$dataset-$variant.json"
        run "$variant" "$scripts/pages.py" "$pair/$variant" > "$raw/phase2-pages-$dataset-$variant-detail.json"
        pages=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$raw/phase2-pages-$dataset-$variant-detail.json")
        run "$variant" "$prior/decode-followup/inspect_data.py" "$pair/$variant" "$pages" > "$raw/phase2-pages-$dataset-$variant.json"
    done
    run final-b "$prior/decode-followup/verify.py" "$pair/final" "$old/$dataset.arrow" > "$raw/phase2-verify-$dataset-final-b.json"
    operations=(scan take)
    if [[ $dataset == wide-unique ]]; then operations+=(repeat128 repeat1024); fi
    for operation in "${operations[@]}"; do
        for trial in 1 2 3; do
            for variant in "${variants[@]}"; do measure "$dataset" "$operation" "$trial" "$variant"; done
        done
        if python3 "$scripts/summarize.py" retry "$raw" "$operation" "$dataset" --phase phase2 --variants base,final,final-b; then
            for trial in 4 5; do
                for variant in "${variants[@]}"; do measure "$dataset" "$operation" "$trial" "$variant"; done
            done
        fi
    done
    # File hashes and per-page encodings are recorded before removing this generated pair.
    rm -rf -- "$pair"
done
