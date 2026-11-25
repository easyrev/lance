#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
variant=$1
trap 'echo $? > "$work/build-$variant.exit"' EXIT
space
test "$(cat "$work/phase1.exit")" = 0
cd "$root/exp-decode"
export CARGO_TARGET_DIR=$work/target-exp
export UV_PROJECT_ENVIRONMENT=$work/venv-exp
export CARGO_BUILD_JOBS=24
export MATURIN_PEP517_ARGS='--profile release-with-debug'
export LANCE_CPU_THREADS=64
git rev-parse HEAD > "$raw/commit-$variant.txt"
git diff --exit-code HEAD --
cargo fmt --all -- --check > "$raw/fmt-$variant.log" 2>&1
set +e
if command -v rtk >/dev/null; then
    rtk cargo test -q -p lance-encoding --profile release-with-debug \
        > "$raw/test-$variant.log" 2>&1
else
    cargo test -q -p lance-encoding --profile release-with-debug \
        > "$raw/test-$variant.log" 2>&1
fi
test_status=$?
set -e
echo "$test_status" > "$raw/test-$variant.exit"
if [[ $variant == exp-B ]]; then
    space
    set +e
    if command -v rtk >/dev/null; then
        rtk cargo clippy -p lance-encoding --tests --profile release-with-debug -- -D warnings \
            > "$raw/clippy-$variant.log" 2>&1
    else
        cargo clippy -p lance-encoding --tests --profile release-with-debug -- -D warnings \
            > "$raw/clippy-$variant.log" 2>&1
    fi
    clippy_status=$?
    echo "$clippy_status" > "$raw/clippy-$variant.exit"
    set -e
    test "$test_status" = 0
    test "$clippy_status" = 0
fi
space
cd python
if [[ $variant == exp-A && ! -x $UV_PROJECT_ENVIRONMENT/bin/python ]]; then
    make install PYTHON=3.12 UV_SYNC='uv sync --frozen --python 3.12 --verbose' \
        > "$raw/install-$variant.log" 2>&1
fi
make build BUILD_SHELL="$scripts/../build-shell" UV_RUN='uv run --frozen --no-sync' \
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
