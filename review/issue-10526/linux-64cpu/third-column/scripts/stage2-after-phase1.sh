#!/usr/bin/env bash
set -euo pipefail
scripts=$(realpath "$(dirname "$0")")
task=/dev/shm/lance-10526/shared-buffer
disk=/root/lance/tmp/shared-buffer-build
raw=$task/raw
trap 'status=$?; echo "$status" > "$disk/raw/stage2-after-phase1.exit"' EXIT
until [[ -s $raw/phase1-complete.exit ]]; do
    if ! tmux has-session -t lance-shared-buffer-finish 2>/dev/null; then exit 1; fi
    sleep 10
done
[[ $(cat "$raw/phase1-complete.exit") == 0 ]]
bash "$scripts/phase2-prepare.sh" > "$raw/phase2-prepare.log" 2>&1
read -r selection < "$raw/phase2-variant.txt"
if [[ $selection == var ]]; then
    git -C /root/lance/shared-buffer-final cherry-pick 6f16adfc7 > "$disk/raw/final-b-var-cherry-pick.log" 2>&1
else
    [[ $selection == pure ]]
    [[ $(git -C /root/lance/shared-buffer-final rev-parse HEAD) == ed0a18841f39f845a8e963fd80cfb4d7689d5d43 ]]
fi
bash "$scripts/build-disk.sh" final-b /root/lance/shared-buffer-final
bash "$scripts/phase2-complete.sh" > "$raw/phase2-complete.log" 2>&1
