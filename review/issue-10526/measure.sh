#!/usr/bin/env bash
set -euo pipefail

if (( $# != 5 )); then
    echo "Usage: $0 BASE_WORKTREE FIX_WORKTREE IPC_DIR SCRATCH_DIR RAW_DIR" >&2
    exit 2
fi

baseline=$1
fix=$2
ipc=$3
scratch=$4
raw=$5
bench=$(realpath "$(dirname "$0")/bench.py")
mkdir -p "$ipc" "$scratch" "$raw"
date +%s.%N > "$raw/measure-start.epoch"
trap 'date +%s.%N > "$raw/measure-exit.epoch"' EXIT
for variant in baseline fix; do
    case "$variant" in
        baseline) checkout=$baseline ;;
        fix) checkout=$fix ;;
    esac
    (
        cd "$checkout/python"
        git rev-parse HEAD
        uv run --frozen --no-sync python -c '
import hashlib
from pathlib import Path
import sys

import lance.lance
import numpy
import pyarrow

extension = Path(lance.lance.__file__).resolve()
with extension.open("rb") as binary:
    digest = hashlib.file_digest(binary, "sha256").hexdigest()
print(f"Python {sys.version.split()[0]}, numpy {numpy.__version__}, pyarrow {pyarrow.__version__}")
print(f"{digest}  {extension}")
'
    ) > "$raw/extension-$variant.txt"
done
if cmp -s <(tail -1 "$raw/extension-baseline.txt" | cut -d' ' -f1) \
          <(tail -1 "$raw/extension-fix.txt" | cut -d' ' -f1); then
    echo "The installed extension digests must differ" >&2
    exit 1
fi
if [[ ! -s "$raw/generate.time" || ! -f "$ipc/wide-unique.arrow" \
    || ! -f "$ipc/wide-repeated.arrow" || ! -f "$ipc/narrow.arrow" ]]; then
    (
        cd "$baseline/python"
        /usr/bin/time -v -o "$raw/generate.time" \
            uv run --frozen --no-sync python "$bench" generate "$ipc"
    ) > "$raw/generate.jsonl"
fi

measure() (
    local variant=$1 kind=$2 writers=$3 threads=$4 label=$5
    shift 5
    case "$variant" in
        baseline) cd "$baseline/python" ;;
        fix) cd "$fix/python" ;;
    esac
    env -u LANCE_FILE_WRITER_MAX_PAGE_BYTES LANCE_CPU_THREADS="$threads" \
        /usr/bin/time -v -o "$raw/$label.time" \
        uv run --frozen --no-sync python "$bench" measure "$ipc/$kind.arrow" "$scratch" \
            --writers "$writers" "$@" > "$raw/$label.json"
)

for kind in wide-unique wide-repeated narrow; do
    for variant in baseline fix; do
        label="file-$kind-$variant"
        if [[ ! -s "$raw/$label.json" ]] || ! grep -q 'Exit status: 0' "$raw/$label.time"; then
            measure "$variant" "$kind" 1 16 "$label" --file-stats
        fi
    done
    (
        cd "$fix/python"
        uv run --frozen --no-sync python "$bench" check-files \
            "$raw/file-$kind-baseline.json" "$raw/file-$kind-fix.json"
    ) | tee -a "$raw/file-checks.jsonl"
done

date +%s.%N > "$raw/write-matrix-start.epoch"
for writers in 1 8; do
    for threads in 8 16; do
        for trial in 1 2 3; do
            for variant in baseline fix; do
                rows_args=()
                if [[ $writers == 8 && -n ${BENCH_8_WRITER_ROWS:-} ]]; then
                    rows_args=(--rows "$BENCH_8_WRITER_ROWS")
                fi
                measure "$variant" wide-unique "$writers" "$threads" \
                    "write-$writers-$threads-$trial-$variant" "${rows_args[@]}"
            done
        done
    done
done

date +%s.%N > "$raw/measure-end.epoch"
