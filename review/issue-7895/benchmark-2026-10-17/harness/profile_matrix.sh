#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ( "$1" != perf && "$1" != heaptrack ) ]]; then
  echo "usage: $0 {perf|heaptrack}" >&2
  exit 2
fi

tool=$1
script=/mnt/lance/bench-9617/harness/profile_one.sh

for source_kind in lance parquet; do
  for variant in upstream pr; do
    echo "[$(date -Ins)] $tool $variant $source_kind"
    "$script" "$tool" "$variant" "$source_kind"
  done
done
