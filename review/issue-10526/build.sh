#!/usr/bin/env bash
set -euo pipefail

if (( $# != 4 )); then
    echo "Usage: $0 BASE_WORKTREE FIX_WORKTREE SHARED_CARGO_TARGET RAW_DIR" >&2
    exit 2
fi

baseline=$1
fix=$2
target=$3
raw=$4
mkdir -p "$target" "$raw"
date +%s.%N > "$raw/measurement-start.epoch"
for variant in baseline fix; do
    case "$variant" in
        baseline) checkout=$baseline ;;
        fix) checkout=$fix ;;
    esac
    (
        cd "$checkout/python"
        git rev-parse HEAD
        printf 'Profile: release-with-debug\nCargo target: %s\n' "$target"
        CARGO_TARGET_DIR="$target" MATURIN_PEP517_ARGS='--profile release-with-debug' \
            /usr/bin/time -v -o "$raw/build-$variant.time" \
            make install PYTHON=3.12 UV_SYNC='uv sync --frozen --python 3.12 --verbose'
    ) > "$raw/build-$variant.log" 2>&1
done
