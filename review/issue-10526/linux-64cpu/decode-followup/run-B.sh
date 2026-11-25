#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'echo $? > "$work/run-B.exit"' EXIT
space
test "$(cat "$work/measure-round-A.exit")" = 0
{
    rustc --version
    cargo --version
    uv --version
    command -v rtk || true
} > "$raw/experiment-tools.txt"
bash "$scripts/build-experiment.sh" exp-B
bash "$scripts/measure-phase2.sh" exp-B
