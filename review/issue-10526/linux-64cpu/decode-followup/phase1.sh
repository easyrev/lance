#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'echo $? > "$work/phase1.exit"' EXIT
space
{ date -u +%FT%TZ; lscpu; free -h; uname -a; ldd --version; } > "$raw/machine.txt"
for version in base final; do
    git -C "$root/$version" rev-parse HEAD > "$raw/commit-$version.txt"
    sha256sum "$root/$version/python/python/lance/lance.abi3.so" > "$raw/extension-$version.sha256"
done
write_data base wide-unique base-default 1
write_data final wide-unique final-default 135
for count in 128 1024; do
    for trial in 1 2 3; do
        for version in base final; do
            space
            run "$version" "$scripts/take.py" "$data/$version-default" "$count" \
                --take-only --repeat 20 > "$raw/repeat-$count-$trial-$version.jsonl"
        done
    done
done
