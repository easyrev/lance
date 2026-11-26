#!/usr/bin/env bash
set -euo pipefail
variant=$1
checkout=$2
disk=/root/lance/tmp/shared-buffer-build
prior=/root/lance/tmp/10526-review/review/issue-10526/linux-64cpu
raw=$disk/raw
mkdir -p "$raw" "$disk/tmp-$variant"
trap 'status=$?; echo "$status" > "$raw/build-$variant.exit"' EXIT
cd "$checkout/python"
git rev-parse HEAD > "$raw/commit-$variant.txt"
git diff --exit-code HEAD --
export CARGO_TARGET_DIR="$disk/target-$variant"
export TMPDIR="$disk/tmp-$variant" UV_PROJECT_ENVIRONMENT="$disk/venv-$variant"
export UV_CACHE_DIR=/root/lance/cache/uv CARGO_BUILD_JOBS=24 LANCE_CPU_THREADS=64
export RUSTC_WRAPPER=""
space() {
    df -h / /dev/shm >> "$raw/build-$variant-space.log"
    for mount in / /dev/shm; do
        if (( $(df -B1 --output=avail "$mount" | tail -1) < 10737418240 )); then
            printf '%s is below 10 GiB\n' "$mount" >> "$raw/build-$variant-space.log"
            return 1
        fi
    done
}
space
uv sync --frozen --python 3.12 --no-install-project > "$raw/dependencies-$variant.log" 2>&1
space
setsid make build BUILD_SHELL="$prior/build-shell" UV_RUN='uv run --frozen --no-sync' \
    --eval='build: override SHELL := $(BUILD_SHELL)' > "$raw/build-$variant.log" 2>&1 &
build_pid=$!
while kill -0 "$build_pid" 2>/dev/null; do
    if ! space; then
        kill -TERM -- "-$build_pid" 2>/dev/null || true
        wait "$build_pid" || true
        exit 3
    fi
    sleep 5
done
wait "$build_pid"
space
uv run --frozen --no-sync python -B -c '
import hashlib
from pathlib import Path
import lance.lance
extension = Path(lance.lance.__file__).resolve()
with extension.open("rb") as binary:
    digest = hashlib.file_digest(binary, "sha256").hexdigest()
    print(f"{digest}  {extension}")
' > "$raw/extension-$variant.sha256"
