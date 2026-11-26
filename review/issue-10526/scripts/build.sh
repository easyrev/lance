#!/usr/bin/env bash
set -euo pipefail
variant=$1
checkout=$2
task=/dev/shm/lance-10526/shared-buffer
prior=/root/lance/tmp/10526-review/review/issue-10526/linux-64cpu
raw=$task/raw
trap 'status=$?; echo "$status" > "$raw/build-$variant.exit"' EXIT
df -h / /dev/shm | tee -a "$raw/space.log"
for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
export CARGO_TARGET_DIR="$task/target-$variant" UV_PROJECT_ENVIRONMENT="$task/venv-$variant"
export UV_CACHE_DIR=/root/lance/cache/uv MATURIN_PEP517_ARGS='--profile release-with-debug'
export CARGO_BUILD_JOBS=24 LANCE_CPU_THREADS=64 TMPDIR="$task/tmp"
if [[ $variant == final ]]; then
    export CARGO_TARGET_DIR=/root/lance/targets/final UV_PROJECT_ENVIRONMENT="$checkout/python/.venv"
fi
cd "$checkout/python"
git rev-parse HEAD > "$raw/commit-$variant.txt"
git diff --exit-code HEAD --
if [[ ! -x $UV_PROJECT_ENVIRONMENT/bin/python ]]; then
    make install PYTHON=3.12 UV_SYNC='uv sync --frozen --python 3.12 --no-install-project --verbose' > "$raw/install-$variant.log" 2>&1
fi
make build BUILD_SHELL="$prior/build-shell" UV_RUN='uv run --frozen --no-sync' \
    --eval='build: override SHELL := $(BUILD_SHELL)' > "$raw/build-$variant.log" 2>&1
uv run --frozen --no-sync python -B -c '
import hashlib
from pathlib import Path
import lance.lance
extension = Path(lance.lance.__file__).resolve()
with extension.open("rb") as binary:
    digest = hashlib.file_digest(binary, "sha256").hexdigest()
    print(f"{digest}  {extension}")
' > "$raw/extension-$variant.sha256"
