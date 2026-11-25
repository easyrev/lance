#!/usr/bin/env bash
set -euo pipefail
umask 022
baseline=$1
fix=$2
ipc=$3
scratch=$4
raw=$5
scripts=$(realpath "$(dirname "$0")")
bench=$scripts/bench.py
mkdir -p "$ipc" "$scratch" "$raw"
cp -n "$scripts/criteria.md" "$raw/criteria.md"
date -u +%FT%TZ > "$raw/measure-start.txt"
trap 'status=$?; echo "$status" > "$raw/measure.exit"; date -u +%FT%TZ > "$raw/measure-end.txt"' EXIT

check_space() {
    local extra=${1:-0} mount available
    df -h / /dev/shm >> "$raw/space.log"
    for mount in / /dev/shm; do
        available=$(df -B1 --output=avail "$mount" | tail -1)
        if (( available < 10*1024**3 )); then
            echo "Insufficient space on $mount for this run ($available bytes available)" >&2
            return 1
        fi
        if [[ $mount == /dev/shm ]] && (( available < 10*1024**3 + extra )); then
            echo "Insufficient /dev/shm space for output and headroom" >&2
            return 1
        fi
    done
}

run() (
    local variant=$1 threads=$2
    shift 2
    local checkout=$baseline
    if [[ $variant == fix ]]; then checkout=$fix; fi
    cd "$checkout/python"
    export LANCE_CPU_THREADS=$threads
    export LANCE_BENCH_PROTO_DIR="$checkout/protos"
    unset LANCE_FILE_WRITER_MAX_PAGE_BYTES
    exec uv run --frozen --no-sync python "$@"
)

check_space
for variant in baseline fix; do
    run "$variant" 64 -c '
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
' > "$raw/extension-$variant.txt"
done
if cmp -s <(tail -1 "$raw/extension-baseline.txt" | cut -d' ' -f1)           <(tail -1 "$raw/extension-fix.txt" | cut -d' ' -f1); then
    echo "The installed extension digests must differ" >&2
    exit 1
fi

check_space $((38*1024**3))
if [[ ! -s $raw/generate.jsonl ]]; then
    run baseline 64 "$bench" generate "$ipc" > "$raw/generate.jsonl.pending"
    mv "$raw/generate.jsonl.pending" "$raw/generate.jsonl"
fi
(cd "$ipc"; sha256sum ./*.arrow) > "$raw/inputs.sha256"

datasets=(wide-unique wide-low-card wide-constant narrow wide-unique-8k wide-repeated wide-template wide-clustered wide-mixed)
for kind in "${datasets[@]}"; do
    (
        pair=$(mktemp -d "$scratch/files-$kind-XXXXXX")
        trap 'rm -rf -- "$pair"' EXIT
        for variant in baseline fix; do
            check_space $((5*1024**3))
            label="file-$kind-$variant"
            run "$variant" 64 "$bench" measure "$ipc/$kind.arrow" "$scratch"                 --writers 1 --file-stats --keep "$pair/$variant" > "$raw/$label.json"
        done
        run fix 64 "$bench" check-files             "$raw/file-$kind-baseline.json" "$raw/file-$kind-fix.json" | tee -a "$raw/file-checks.jsonl"
        for variant in baseline fix; do
            check_space
            run "$variant" 64 "$bench" read "$pair/$variant" "$ipc/$kind.arrow" verify                 > "$raw/verify-$kind-$variant.json"
        done
        for operation in scan take; do
            for trial in 1 2 3; do
                for variant in baseline fix; do
                    check_space
                    run "$variant" 64 "$bench" read "$pair/$variant" "$ipc/$kind.arrow" "$operation"                         > "$raw/$operation-$kind-$trial-$variant.json"
                    if [[ $operation == take && $trial == 3 ]]; then
                        rm -rf -- "$pair/$variant"
                    fi
                done
            done
        done
    )
done

measure() {
    local kind=$1 writers=$2 threads=$3 trial=$4
    for variant in baseline fix; do
        # Reserve enough for eight outputs even if they occupy the raw payload size.
        check_space $(( writers == 8 ? 12*1024**3 : 5*1024**3 ))
        run "$variant" "$threads" "$bench" measure "$ipc/$kind.arrow" "$scratch"             --writers "$writers" > "$raw/write-$kind-$writers-$threads-$trial-$variant.json"
    done
}

date -u +%FT%TZ > "$raw/write-matrix-start.txt"
for writers in 1 8; do
    kind=wide-unique
    if [[ $writers == 8 ]]; then kind=wide-unique-8k; fi
    for threads in 8 64; do
        for trial in warmup 1 2 3; do
            measure "$kind" "$writers" "$threads" "$trial"
        done
    done
done
for kind in wide-clustered wide-mixed; do
    for trial in 1 2 3; do
        measure "$kind" 1 64 "$trial"
    done
done
