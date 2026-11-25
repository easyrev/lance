#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'echo $? > "$raw/test-exp-A.exit"' EXIT
space
cd "$root/exp-decode"
export CARGO_TARGET_DIR=$work/target-exp
export CARGO_BUILD_JOBS=24
git rev-parse HEAD > "$raw/test-exp-A-commit.txt"
cargo fmt --all -- --check > "$raw/fmt-exp-A.log" 2>&1
if command -v rtk >/dev/null; then
    rtk cargo test -q -p lance-encoding --profile release-with-debug \
        > "$raw/test-exp-A.log" 2>&1
else
    cargo test -q -p lance-encoding --profile release-with-debug \
        > "$raw/test-exp-A.log" 2>&1
fi
