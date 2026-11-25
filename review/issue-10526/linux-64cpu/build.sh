#!/bin/bash
set -euo pipefail
root=${LANCE_BENCH_ROOT:-/root/lance}
scripts=$(realpath "$(dirname "$0")")
raw=/dev/shm/lance-10526/raw
mkdir -p "$raw"
rm -f "$raw/build.exit"
trap 'echo $? > "$raw/build.exit"' EXIT
{ lscpu; free -h; cat /etc/os-release; uname -a; df -h / /dev/shm; } > "$raw/machine.txt"
for variant in base final; do
    for mount in / /dev/shm; do
        (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 ))
    done
    cd "$root/$variant/python"
    export CARGO_TARGET_DIR="$root/targets/$variant"
    export UV_CACHE_DIR="$root/cache/uv"
    export MATURIN_PEP517_ARGS='--profile release-with-debug'
    export CARGO_BUILD_JOBS=24
    {
        git rev-parse HEAD
        rustc --version
        uv --version
        time make install PYTHON=3.12 UV_SYNC='uv sync --frozen --python 3.12 --verbose'
        time make build BUILD_SHELL="$scripts/build-shell" UV_RUN='uv run --frozen --no-sync' --eval='build: override SHELL := $(BUILD_SHELL)'
    } > "$raw/build-$variant.log" 2>&1
done
