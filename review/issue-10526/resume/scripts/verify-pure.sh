#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
disk=/root/lance/tmp/shared-buffer-build
raw=$task/raw
prior=/root/lance/tmp/10526-review/review/issue-10526/linux-64cpu
export LANCE_CPU_THREADS=64 TMPDIR=$disk/tmp UV_CACHE_DIR=/root/lance/cache/uv UV_PROJECT_ENVIRONMENT=$disk/venv-pure
trap 'status=$?; echo "$status" > "$raw/verify-pure.exit"' EXIT
df -h / /dev/shm | tee -a "$raw/space.log"
for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
[[ $(cat "$disk/raw/build-pure.exit") == 0 ]]
cd /root/lance/shared-buffer-pure/python
for dataset in utf8-1page utf8-zstd-25k utf8-zstd-8k binary-zstd-varlen binary-random-varlen binary-zstd-medium binary-medium-default mixed; do
    echo "$dataset"
    case $dataset in
        utf8-1page|utf8-zstd-25k) input=/dev/shm/lance-10526/ipc/wide-unique.arrow ;;
        utf8-zstd-8k) input=/dev/shm/lance-10526/ipc/wide-unique-8k.arrow ;;
        binary-medium-default) input=$task/ipc/binary-zstd-medium.arrow ;;
        *) input=$task/ipc/$dataset.arrow ;;
    esac
    uv run --frozen --no-sync python -B "$prior/decode-followup/verify.py" "$task/data/$dataset" "$input" > "$raw/phase1-verify-$dataset-pure.json"
done
