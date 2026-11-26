#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'status=$?; echo "$status" > "$raw/run.exit"' EXIT
until [[ -s "$raw/build.exit" ]]; do sleep 10; done
[[ $(cat "$raw/build.exit") == 0 ]]
for stage in environment data verify measure; do
    printf '%s %s\n' "$(date -u +%FT%TZ)" "$stage"
    bash "$disk/scripts/$stage.sh" > "$raw/$stage.log" 2>&1
done
python3 "$disk/scripts/report.py" "$disk" p1 > "$raw/report.log" 2>&1
python3 "$disk/scripts/deliver.py" "$disk" > "$raw/deliver.log" 2>&1
