#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
disk=/root/lance/tmp/shared-buffer-build
prior=/root/lance/tmp/10526-review/review/issue-10526/linux-64cpu
scripts=$(realpath "$(dirname "$0")")
raw=$task/raw
old=/dev/shm/lance-10526/ipc
export LANCE_CPU_THREADS=64 TMPDIR=$disk/tmp UV_CACHE_DIR=/root/lance/cache/uv
unset LANCE_FILE_WRITER_MAX_PAGE_BYTES
trap 'status=$?; echo "$status" > "$raw/phase2-prepare.exit"' EXIT
[[ $(cat "$raw/phase1-complete.exit") == 0 ]]
space() {
    df -h / /dev/shm >> "$raw/phase2-space.log"
    for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
}
space
printf 'Estimated base and final .lance files: 12172885724 bytes.\n' >> "$raw/phase2-space.log"
[[ $(git -C /root/lance/final rev-parse HEAD) == d0020f4291a0cb18790ac731df7c24890a169ca1 ]]
sha256sum -c "$prior/decode-followup/raw/extension-final.sha256"
sha256sum -c "$disk/previous-build-records/extension-base.sha256"
datasets=(wide-unique wide-unique-8k wide-low-card wide-repeated wide-template wide-clustered wide-mixed wide-constant narrow)
run() (
    local variant=$1 checkout=/root/lance/$1
    shift
    export UV_PROJECT_ENVIRONMENT=$checkout/python/.venv
    export LANCE_BENCH_PROTO_DIR=$checkout/protos
    cd "$checkout/python"
    exec uv run --frozen --no-sync python -B "$@"
)
for dataset in "${datasets[@]}"; do
    pair=$task/phase2/$dataset
    mkdir -p "$pair"
    for variant in base final; do
        space
        echo "$dataset $variant"
        run "$variant" "$prior/bench.py" measure "$old/$dataset.arrow" "$pair" --writers 1 --file-stats --keep "$pair/$variant" > "$raw/phase2-write-$dataset-$variant.json"
        run "$variant" "$scripts/pages.py" "$pair/$variant" > "$raw/phase2-pages-$dataset-$variant-detail.json"
        pages=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["pages"])' "$raw/phase2-write-$dataset-$variant.json")
        run "$variant" "$prior/decode-followup/inspect_data.py" "$pair/$variant" "$pages" > "$raw/phase2-pages-$dataset-$variant.json"
    done
done
python3 "$scripts/check-phase2-layout.py" "$raw" > "$raw/phase2-variant.txt"
