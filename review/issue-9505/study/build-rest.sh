#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
wait_build() {
    local variant="$1"
    while [[ ! -f "$run_root/logs/${variant}-build-exit-code" ]]; do sleep 10; done
    test "$(cat "$run_root/logs/${variant}-build-exit-code")" = 0
}
lane_one() {
    wait_build B
    bash "$run_root/build-one.sh" DB > "$run_root/logs/DB-driver.log" 2>&1
    bash "$run_root/build-one.sh" DP > "$run_root/logs/DP-driver.log" 2>&1
}
lane_two() {
    wait_build P
    bash "$run_root/build-one.sh" CTX > "$run_root/logs/CTX-driver.log" 2>&1
}
lane_one &
first=$!
lane_two &
second=$!
wait "$first"
wait "$second"
date -u --iso-8601=seconds > "$run_root/logs/build-rest-complete"
