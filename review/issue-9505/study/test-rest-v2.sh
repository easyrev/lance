#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
for variant in CTX DB; do
    while [[ ! -f "$run_root/logs/${variant}-build-exit-code" ]]; do sleep 10; done
    test "$(cat "$run_root/logs/${variant}-build-exit-code")" = 0
done
bash "$run_root/test-rust.sh" DB > "$run_root/logs/DB-rust-driver.log" 2>&1 &
first=$!
bash "$run_root/test-rust.sh" DP > "$run_root/logs/DP-rust-driver.log" 2>&1 &
second=$!
wait "$first"
wait "$second"
date -u --iso-8601=seconds > "$run_root/logs/test-rest-complete"
