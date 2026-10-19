#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/hypotheses-9505-20261019
checkout=/mnt/lance/checkouts/hypotheses-9505
source /mnt/lance/env.sh
source /mnt/lance/proxy.sh
proxy-on >/dev/null
export CARGO_TARGET_DIR=/mnt/lance/targets/hypotheses-9505
export CARGO_BUILD_JOBS=6
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/build-probe-exit-code"' EXIT
cd "$checkout"
cargo fmt --all
cargo test -p lance --lib dataset::write::merge_insert::hypotheses --profile release-with-debug --locked --no-run --message-format=json > "$run_root/logs/build-artifacts.jsonl" 2> "$run_root/logs/build-stderr.log"
date -u --iso-8601=seconds
