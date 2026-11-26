#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
prior=/root/lance/tmp/10526-review/review/issue-10526/linux-64cpu
raw=$task/raw
export LANCE_CPU_THREADS=64
trap 'status=$?; echo "$status" > "$raw/verify-base.exit"' EXIT
df -h / /dev/shm | tee -a "$raw/space.log"
for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
for dataset in utf8-1page utf8-zstd-25k utf8-zstd-8k binary-zstd-varlen binary-random-varlen binary-zstd-medium mixed; do
    echo "$dataset"
    case $dataset in
        utf8-1page|utf8-zstd-25k) input=/dev/shm/lance-10526/ipc/wide-unique.arrow ;;
        utf8-zstd-8k) input=/dev/shm/lance-10526/ipc/wide-unique-8k.arrow ;;
        *) input=$task/ipc/$dataset.arrow ;;
    esac
    uv run --frozen --no-sync python -B "$prior/decode-followup/verify.py" "$task/data/$dataset" "$input" > "$raw/phase1-verify-$dataset-base.json"
done
