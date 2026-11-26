#!/usr/bin/env bash
set -euo pipefail
scripts=$(realpath "$(dirname "$0")")
disk=/root/lance/tmp/shared-buffer-build
raw=$disk/raw/attribution
task=/dev/shm/lance-10526/shared-buffer
export LANCE_CPU_THREADS=64 TMPDIR=$disk/tmp UV_CACHE_DIR=/root/lance/cache/uv
group=lance10526attr
probe_names=()
cleanup() {
    local status=$?
    for event in "${probe_names[@]}"; do perf probe --del "$event" >> "$raw/probe-cleanup.log" 2>&1 || true; done
    echo "$status" > "$raw/probe.exit"
}
trap cleanup EXIT
for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
for variant in base pure var; do
    checkout=/root/lance/shared-buffer-$variant
    export UV_PROJECT_ENVIRONMENT=$disk/venv-$variant
    if [[ $variant == base ]]; then
        checkout=/root/lance/base
        export UV_PROJECT_ENVIRONMENT=$checkout/python/.venv
    fi
    so=$checkout/python/python/lance/lance.abi3.so
    readelf -lW "$so" > "$raw/program-headers-$variant.txt"
    events=()
    for kind in concat fast; do
        if [[ $kind == concat ]]; then
            pattern='21concat_decoded_arrays$'
        else
            pattern='25VariableFullZipDecodeTask.*20decode_variable_into$'
        fi
        addr=$(awk -v pattern="$pattern" '$3 ~ pattern {print $1}' "$raw/symbols-$variant.txt")
        if [[ $kind == fast && $variant == base ]]; then [[ -z $addr ]]; continue; fi
        [[ $addr =~ ^[a-f0-9]+$ ]]
        file_addr=$(python3 - "$addr" "$raw/program-headers-$variant.txt" <<'PY'
import sys
addr = int(sys.argv[1], 16)
with open(sys.argv[2]) as stream:
    for line in stream:
        parts = line.split()
        if parts and parts[0] == "LOAD":
            offset, virtual, _, size = (int(x, 16) for x in parts[1:5])
            if virtual <= addr < virtual + size:
                print(hex(addr - virtual + offset))
                break
    else:
        raise RuntimeError("Symbol is outside file-backed load segments")
PY
)
        event=$group:${variant}_$kind
        perf probe --no-inlines -x "$so" --add "$event=$file_addr" >> "$raw/probe-registration.log" 2>&1
        printf '%s\t%s\t%s\n' "$event" "$addr" "$file_addr" >> "$raw/probe-addresses.tsv"
        probe_names+=("$event")
        events+=(-e "$event")
    done
    cd "$checkout/python"
    perf stat -x , --no-big-num -o "$raw/probe-$variant-take128.csv" "${events[@]}" -- uv run --frozen --no-sync python -B "$scripts/take.py" "$task/data/utf8-1page" 128 --dataset-rows 25000 --take-only > "$raw/probe-$variant-take128.json"
    perf stat -x , --no-big-num -o "$raw/probe-$variant-scan.csv" "${events[@]}" -- uv run --frozen --no-sync python -B "$scripts/scan.py" "$task/data/utf8-1page" 25000 > "$raw/probe-$variant-scan.json"
    if [[ $variant != base ]]; then
        perf stat -x , --no-big-num -o "$raw/probe-$variant-multipage-control.csv" "${events[@]}" -- uv run --frozen --no-sync python -B "$scripts/take.py" "$task/data/utf8-zstd-25k" 128 --dataset-rows 25000 --take-only > "$raw/probe-$variant-multipage-control.json"
    fi
done
