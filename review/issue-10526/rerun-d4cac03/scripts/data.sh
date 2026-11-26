#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'status=$?; echo "$status" > "$raw/data.exit"' EXIT
space
mkdir -p "$task"/{ipc,p1} "$raw/data"
run base "$disk/scripts/generate-utf8.py" "$task/ipc" > "$raw/data/generate-utf8.jsonl"
write() {
    local name=$1 input=$2 batches=$3 zstd=$4 variable=$5
    shift 5
    space
    printf '%s %s\n' "$(date -u +%FT%TZ)" "$name"
    run base "$tools/prepare.py" write "$task/ipc/$input.arrow" "$task/p1/$name" "$@" > "$raw/data/write-$name.json"
    run base "$tools/pages.py" "$task/p1/$name" > "$raw/data/pages-$name-detail.json"
    local observed
    observed=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$raw/data/pages-$name-detail.json")
    run base "$tools/reused/inspect_data.py" "$task/p1/$name" "$observed" > "$raw/data/pages-$name.json"
    run base "$disk/scripts/check-pages.py" "$raw/data" "$name" "$batches" "$zstd" "$variable"
}
generate() {
    space
    run base "$tools/prepare.py" generate "$task/ipc/$1.arrow" "${@:2}"
}
write utf8-1page wide-unique 1 1 0
write utf8-zstd-25k wide-unique 142 142 0 --stream
write utf8-zstd-8k wide-unique-8k 46 46 0 --stream
generate binary-zstd-varlen 12000 65536 524288
write binary-zstd-varlen binary-zstd-varlen 110 110 0 --stream
generate binary-random-varlen 12000 65536 524288 --random-bytes
write binary-random-varlen binary-random-varlen 110 110 0 --stream
generate binary-zstd-medium 99650 8192 32768
write binary-zstd-medium binary-zstd-medium 63 63 0 --stream --zstd
write binary-medium-default binary-zstd-medium 63 0 63 --stream
generate mixed 16000 8192 16384 --mixed
write mixed mixed 28 25 3 --stream
sha256sum "$task"/ipc/*.arrow > "$raw/data/inputs.sha256"
