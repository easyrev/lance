#!/usr/bin/env bash
set -euo pipefail

if (( $# == 4 )); then
    variants=(baseline fix)
elif (( $# == 5 )) && [[ $5 == --fix-only ]]; then
    variants=(fix)
else
    echo "Usage: $0 BASE_WORKTREE FIX_WORKTREE SHARED_CARGO_TARGET RAW_DIR [--fix-only]" >&2
    exit 2
fi

baseline=$1
fix=$2
target=$3
raw=$4
mkdir -p "$target" "$raw"
date +%s.%N > "$raw/measurement-start.epoch"
for variant in "${variants[@]}"; do
    case "$variant" in
        baseline) checkout=$baseline ;;
        fix) checkout=$fix ;;
    esac
    (
        cd "$checkout/python"
        git rev-parse HEAD
        printf 'Profile: release-with-debug\nCargo target: %s\n' "$target"
        export CARGO_TARGET_DIR="$target"
        export MATURIN_PEP517_ARGS='--profile release-with-debug'
        if (( $# == 5 )); then
            /usr/bin/time -v -o "$raw/build-$variant.time" \
                uv sync --frozen --python 3.12 --verbose --reinstall-package pylance
        else
            /usr/bin/time -v -o "$raw/build-$variant.time" \
                make install PYTHON=3.12 UV_SYNC='uv sync --frozen --python 3.12 --verbose'
        fi
    ) > "$raw/build-$variant.log" 2>&1
done
