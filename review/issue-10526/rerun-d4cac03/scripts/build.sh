#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'status=$?; echo "$status" > "$raw/build.exit"' EXIT
for variant in base head; do
    space
    resolve "$variant"
    export CARGO_TARGET_DIR="$disk/target-$variant" UV_PROJECT_ENVIRONMENT="$environment"
    export MATURIN_PEP517_ARGS='--profile release-with-debug' CARGO_BUILD_JOBS=24
    export RUSTC_WRAPPER=""
    (
        cd "$checkout/python"
        git rev-parse HEAD > "$raw/commit-$variant.txt"
        git diff --exit-code HEAD --
        make install PYTHON=3.12 UV_SYNC='uv sync --frozen --python 3.12 --no-install-project --verbose'
    ) > "$raw/install-$variant.log" 2>&1
    (
        cd "$checkout/python"
        make build BUILD_SHELL="$tools/reused/build-shell" UV_RUN='uv run --frozen --no-sync' \
            --eval='build: override SHELL := $(BUILD_SHELL)'
    ) > "$raw/build-$variant.log" 2>&1
    sha256sum "$extension" > "$raw/extension-$variant.sha256"
done
