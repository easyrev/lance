#!/usr/bin/env bash
set -eu
ev=$(cd "$(dirname "$0")" && pwd)
export LANCE_CPU_THREADS=8
rounds=${1:-5}
tag=${2:-first}
shift "$(( $# < 2 ? $# : 2 ))"
if (( $# )); then workloads=("$@"); else
    workloads=(unique consecutive template constant dirty-null mostly-wide mostly-short)
fi
read -r -a variants <<< "${VARIANTS:-baseline fix p1 p2}"
out="$ev/$tag.tsv"
printf 'variant\tround\tversion\tworkload\ttrial\tfile_bytes\tpages\tmax_raw_bytes\tmax_encoded_bytes\twrite_ms\tread_ms\tpage_rows\tlayouts\n' > "$out"
for workload in "${workloads[@]}"; do
    for ((round=0; round<rounds; round++)); do
        for ((index=0; index<${#variants[@]}; index++)); do
            variant=${variants[$(((index + round) % ${#variants[@]}))]}
            result=$("$ev/writer-$variant" "$workload" 2.2 1)
            printf '%s\t%s\t%s\n' "$variant" "$round" "$result" >> "$out"
        done
    done
done
