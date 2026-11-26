#!/usr/bin/env bash
set -euo pipefail
scripts=$(realpath "$(dirname "$0")")
disk=/root/lance/tmp/shared-buffer-build
raw=$disk/raw/attribution
task=/dev/shm/lance-10526/shared-buffer
export LANCE_CPU_THREADS=64 TMPDIR=$disk/tmp UV_CACHE_DIR=/root/lance/cache/uv
trap 'status=$?; echo "$status" > "$raw/attribution.exit"' EXIT
df -h / /dev/shm > "$raw/space.log"
for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
for variant in base pure var; do
    checkout=/root/lance/shared-buffer-$variant
    if [[ $variant == base ]]; then checkout=/root/lance/base; fi
    extension=$checkout/python/python/lance/lance.abi3.so
    stat -c '%s %n' "$extension" > "$raw/file-size-$variant.txt"
    size -A "$extension" > "$raw/size-A-$variant.txt"
    nm -an --defined-only "$extension" | awk '/21concat_decoded_arrays$|25VariableFullZipDecodeTask.*20decode_variable_into$|34StructuralCompositeDecodeArrayTask15decode_variable/' > "$raw/symbols-$variant.txt"
done
for trial in 1 2 3 4 5; do
    for variant in base pure var; do
        (
            checkout=/root/lance/shared-buffer-$variant
            export UV_PROJECT_ENVIRONMENT=$disk/venv-$variant
            if [[ $variant == base ]]; then
                checkout=/root/lance/base
                export UV_PROJECT_ENVIRONMENT=$checkout/python/.venv
            fi
            cd "$checkout/python"
            uv run --frozen --no-sync python -B "$scripts/take-rss-stages.py" "$task/data/utf8-1page" 128 --dataset-rows 25000 --take-only
        ) > "$raw/checkpoints-$trial-$variant.json"
    done
done
