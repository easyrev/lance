#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/hypotheses-9505-20261019
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/prepare-exit-code"' EXIT
source /mnt/lance/env.sh
cd /mnt/lance/checkouts/U_main/python
uv run --no-sync python "$run_root/scripts/prepare.py"
