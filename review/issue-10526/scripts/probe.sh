#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
prior=/root/lance/tmp/10526-review/review/issue-10526/linux-64cpu
scripts=$(realpath "$(dirname "$0")")
export LANCE_CPU_THREADS=64
unset LANCE_FILE_WRITER_MAX_PAGE_BYTES
trap 'status=$?; echo "$status" > "$task/raw/probe.exit"' EXIT
df -h / /dev/shm | tee -a "$task/raw/space.log"
for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
mkdir -p "$task/ipc" "$task/data"
run() { uv run --frozen --no-sync python -B "$@"; }
inspect() {
    local name=$1 rows=$2
    run "$scripts/pages.py" "$task/data/$name" > "$task/raw/pages-$name-detail.json"
    local pages
    pages=$(run -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$task/raw/pages-$name-detail.json")
    run "$prior/decode-followup/inspect_data.py" "$task/data/$name" "$pages" > "$task/raw/pages-$name.json"
    (( pages >= rows ))
}
run "$scripts/prepare.py" generate "$task/ipc/binary-random-varlen.arrow" 12000 65536 524288 --random-bytes
run "$scripts/prepare.py" write "$task/ipc/binary-random-varlen.arrow" "$task/data/binary-random-varlen" --stream > "$task/raw/write-binary-random-varlen.json"
inspect binary-random-varlen 2
for size in 255 256 8192 32768 32769; do
    name=layout-probe-$size
    run "$scripts/prepare.py" generate "$task/ipc/$name.arrow" 1024 "$size" "$size"
    run "$scripts/prepare.py" write "$task/ipc/$name.arrow" "$task/data/$name" > "$task/raw/write-$name.json"
    inspect "$name" 1
done
