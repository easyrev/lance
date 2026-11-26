#!/usr/bin/env bash
set -euo pipefail
root=/root/lance
work=/dev/shm/lance-10526/decode-followup
original=/dev/shm/lance-10526
scripts=$(realpath "$(dirname "${BASH_SOURCE[0]}")")
bench=$scripts/../bench.py
raw=$work/raw
data=$work/data
mkdir -p "$raw" "$data" "$work/tmp"
export TMPDIR=$work/tmp
export UV_CACHE_DIR=$root/cache/uv
export LANCE_CPU_THREADS=64
unset LANCE_FILE_WRITER_MAX_PAGE_BYTES

space() {
    df -h / /dev/shm | tee -a "$raw/space.log"
    local mount available
    for mount in / /dev/shm; do
        available=$(df -B1 --output=avail "$mount" | tail -1)
        if (( available < 10 * 1024**3 )); then
            echo "Insufficient space on $mount ($available bytes available)" >&2
            return 1
        fi
    done
}

run() (
    local checkout=$root/$1
    shift
    cd "$checkout/python"
    export LANCE_BENCH_PROTO_DIR=$checkout/protos
    exec uv run --frozen --no-sync python -B "$@"
)

write_data() {
    local checkout=$1 kind=$2 name=$3 pages=$4 input=$original/ipc/$2.arrow
    space
    sha256sum "$input" >> "$raw/inputs.sha256"
    local previous=$original/take-investigation/data/$name
    if [[ $name == *-default && -d $previous ]]; then
        ln -s "$previous" "$data/$name"
    else
        run "$checkout" "$bench" measure "$input" "$data" --writers 1 \
            --file-stats --keep "$data/$name" > "$raw/file-$name.json"
    fi
    run "$checkout" "$scripts/inspect_data.py" "$data/$name" "$pages" \
        > "$raw/pages-$name.json"
}
