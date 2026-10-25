#!/usr/bin/env bash
set -euo pipefail
# The earlier validation chain uses a runner that lacks the final phase alias.
# Preserve that runner and its logs. Continue only after required checks pass.
while tmux has-session -t lance-issue10096-final 2>/dev/null; do
    sleep 3
done
for phase in fixed-tests-final index-tests-final fixed-lint-final; do
    [[ $(cat "/mnt/lance/results/issue10096/$phase/exit.code") == 0 ]]
done
bash /mnt/lance/results/issue10096-run-v7.sh example-lint-default-final-v2
bash /mnt/lance/results/issue10096-run-v7.sh fixed-build
