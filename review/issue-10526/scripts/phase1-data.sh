#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
old=/dev/shm/lance-10526/ipc
prior=/root/lance/tmp/10526-review/review/issue-10526/linux-64cpu
scripts=$(realpath "$(dirname "$0")")
export LANCE_CPU_THREADS=64
unset LANCE_FILE_WRITER_MAX_PAGE_BYTES
trap 'status=$?; echo "$status" > "$task/raw/phase1-data.exit"' EXIT
df -h / /dev/shm | tee -a "$task/raw/space.log"
for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
run() { uv run --frozen --no-sync python -B "$@"; }
write() {
    local name=$1 input=$2 mode=$3
    shift 3
    run "$scripts/prepare.py" write "$input" "$task/data/$name" "$@" > "$task/raw/write-$name.json"
    run "$scripts/pages.py" "$task/data/$name" > "$task/raw/pages-$name-detail.json"
    local pages
    pages=$(run -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$task/raw/pages-$name-detail.json")
    run "$prior/decode-followup/inspect_data.py" "$task/data/$name" "$pages" > "$task/raw/pages-$name.json"
    if [[ $mode == single ]]; then (( pages == 1 )); else (( pages > 1 )); fi
}
write utf8-1page "$old/wide-unique.arrow" single
write utf8-zstd-25k "$old/wide-unique.arrow" multiple --stream
write utf8-zstd-8k "$old/wide-unique-8k.arrow" multiple --stream
run "$scripts/prepare.py" generate "$task/ipc/binary-zstd-varlen.arrow" 12000 65536 524288
write binary-zstd-varlen "$task/ipc/binary-zstd-varlen.arrow" multiple --stream
run "$scripts/prepare.py" generate "$task/ipc/binary-zstd-medium.arrow" 99650 8192 32768
write binary-zstd-medium "$task/ipc/binary-zstd-medium.arrow" multiple --stream --zstd
run "$scripts/prepare.py" generate "$task/ipc/mixed.arrow" 16000 8192 16384 --mixed
write mixed "$task/ipc/mixed.arrow" multiple --stream
sha256sum "$old"/*.arrow "$task"/ipc/{binary-*,mixed}.arrow > "$task/raw/inputs.sha256"
