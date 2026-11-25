#!/bin/bash
set -euo pipefail
root=${LANCE_BENCH_ROOT:-/root/lance}
work=/dev/shm/lance-10526
scripts=$(realpath "$(dirname "$0")")
while [[ ! -s $work/raw/build.exit ]]; do sleep 20; done
[[ $(cat "$work/raw/build.exit") == 0 ]]
export UV_CACHE_DIR="$root/cache/uv"
bash "$scripts/measure.sh" "$root/base" "$root/final" "$work/ipc" "$work/scratch" "$work/raw"     > "$work/raw/measure.log" 2>&1
cd "$root/base/python"
uv run --frozen --no-sync python "$scripts/summarize.py" "$work/raw" > "$work/summary.md"
