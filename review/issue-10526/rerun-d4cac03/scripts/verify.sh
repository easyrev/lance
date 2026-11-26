#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'status=$?; echo "$status" > "$raw/verify.exit"' EXIT
space
mkdir -p "$raw/exact"
for dataset in "${datasets[@]}"; do
    case "$dataset" in
        utf8-1page|utf8-zstd-25k) input=wide-unique ;;
        utf8-zstd-8k) input=wide-unique-8k ;;
        binary-medium-default) input=binary-zstd-medium ;;
        *) input=$dataset ;;
    esac
    for build in base head; do
        printf '%s %s %s\n' "$(date -u +%FT%TZ)" "$dataset" "$build"
        run "$build" "$disk/scripts/verify.py" "$task/p1/$dataset" "$task/ipc/$input.arrow" > "$raw/exact/$dataset-$build.json"
    done
    cmp "$raw/exact/$dataset-base.json" "$raw/exact/$dataset-head.json"
done
