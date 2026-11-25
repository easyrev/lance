#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'echo $? > "$work/prepare-phase2.exit"' EXIT
space
test "$(cat "$work/phase1.exit")" = 0
write_data base wide-unique-8k base-wide-unique-8k 1
write_data final wide-unique-8k final-wide-unique-8k 44
write_data final wide-mixed final-wide-mixed 128
