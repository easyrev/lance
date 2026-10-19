#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/start-when-ready-exit-code"' EXIT
checks=(B-build P-build CTX-build DB-build DP-build U-python B-python P-python D-python CTX-python DB-python DP-python DB-rust DP-rust P-integration DP-integration)
while true; do
    ready=true
    for check in "${checks[@]}"; do
        path="$run_root/logs/${check}-exit-code"
        if [[ -f "$path" ]]; then
            test "$(cat "$path")" = 0 || { echo "Failed prerequisite: $check"; exit 1; }
        else
            ready=false
        fi
    done
    for marker in build-rest-complete test-rest-complete test-python-rest-complete; do
        [[ -f "$run_root/logs/$marker" ]] || ready=false
    done
    if "$ready"; then break; fi
    sleep 10
done
date -u --iso-8601=seconds
ps -eo pid,ppid,comm,pcpu,rss --sort=-pcpu > "$run_root/environment/processes-before-performance.txt"
bash "$run_root/run-first-wave.sh" > "$run_root/logs/first-wave.log" 2>&1
