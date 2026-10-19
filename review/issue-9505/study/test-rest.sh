#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
wait_build() {
    local variant="$1"
    while [[ ! -f "$run_root/logs/${variant}-build-exit-code" ]]; do sleep 10; done
    test "$(cat "$run_root/logs/${variant}-build-exit-code")" = 0
}
wait_build CTX
wait_build DB
bash "$run_root/test-rust.sh" DB > "$run_root/logs/DB-rust-driver.log" 2>&1
wait_build DP
bash "$run_root/test-rust.sh" DP > "$run_root/logs/DP-rust-driver.log" 2>&1
date -u --iso-8601=seconds > "$run_root/logs/test-rest-complete"
