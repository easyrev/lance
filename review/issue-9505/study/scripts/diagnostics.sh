#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/hypotheses-9505-20261019
source /mnt/lance/env.sh
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/diagnostics-exit-code"' EXIT
cd /mnt/lance/checkouts/U_main/python
uv run --no-sync python "$run_root/scripts/run.py" freeze
uv run --no-sync python "$run_root/scripts/run.py" diagnostics
