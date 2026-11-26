#!/usr/bin/env bash
set -euo pipefail
scripts=$(realpath "$(dirname "$0")")
task=/dev/shm/lance-10526/shared-buffer
disk=/root/lance/tmp/shared-buffer-build
trap 'status=$?; echo "$status" > "$disk/raw/checks-after-stage2.exit"' EXIT
until [[ -s $task/raw/phase2-complete.exit ]]; do
    if ! tmux has-session -t lance-shared-buffer-stage2 2>/dev/null; then exit 1; fi
    sleep 10
done
[[ $(cat "$task/raw/phase2-complete.exit") == 0 ]]
bash "$scripts/run-final-checks.sh" pure
