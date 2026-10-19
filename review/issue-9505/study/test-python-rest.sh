#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
bash "$run_root/test-python.sh" D > "$run_root/logs/D-python-driver.log" 2>&1
for variant in B P CTX DB DP; do
    while [[ ! -f "$run_root/logs/${variant}-build-exit-code" ]]; do sleep 10; done
    test "$(cat "$run_root/logs/${variant}-build-exit-code")" = 0
    bash "$run_root/test-python.sh" "$variant" > "$run_root/logs/${variant}-python-driver.log" 2>&1
done
date -u --iso-8601=seconds > "$run_root/logs/test-python-rest-complete"
