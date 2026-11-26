#!/usr/bin/env bash
set -euo pipefail
disk=$(realpath "$(dirname "${BASH_SOURCE[0]}")/..")
raw=$disk/raw
task=/dev/shm/lance-pr1-rerun
tools=$disk/reused/scripts
export LANCE_CPU_THREADS=64 TMPDIR=$disk/tmp UV_CACHE_DIR=/root/lance/cache/uv
unset LANCE_FILE_WRITER_MAX_PAGE_BYTES PYTHONPATH PYTHONHOME VIRTUAL_ENV
space() {
    { date -u +%FT%TZ; df -h / /dev/shm; } >> "$raw/space.log"
    for mount in / /dev/shm; do
        if (( $(df -B1 --output=avail "$mount" | tail -1) < 10737418240 )); then
            echo "Less than 10 GiB available on $mount" >&2
            return 1
        fi
    done
}
resolve() {
    checkout=$disk/$1
    environment=$disk/env-$1
    extension=$checkout/python/python/lance/lance.abi3.so
}
run() (
    resolve "$1"; shift
    cd "$disk"
    exec "$environment/bin/python" -B "$@"
)
datasets=(utf8-1page utf8-zstd-25k utf8-zstd-8k binary-zstd-varlen binary-random-varlen binary-zstd-medium binary-medium-default mixed)
row_counts=(25000 25000 8000 12000 12000 99650 99650 16000)
