#!/usr/bin/env bash
set -eu
ev=$(cd "$(dirname "$0")" && pwd)
export LANCE_CPU_THREADS=8
cp /dev/null "$ev/version-smoke.tsv"
sed -n '1p' "$ev/first.tsv" > "$ev/version-smoke.tsv"
for version in 2.1 2.3; do
    for kind in unique consecutive template constant dirty-null mostly-wide mostly-short; do
        for variant in fix p1-compatible p2-compatible; do
            result=$("$ev/writer-$variant" "$kind" "$version" 1)
            printf '%s\t0\t%s\n' "$variant" "$result" >> "$ev/version-smoke.tsv"
        done
    done
done
