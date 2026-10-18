#!/usr/bin/env bash
set -euo pipefail
source /mnt/lance/env.sh
cd /mnt/lance/checkouts/K_check/python
final_root=/mnt/lance/killer-merge-final-20261019
trap 'task_exit=$?; printf "%s\n" "$task_exit" > "$final_root/pairs-and-audit-exit-code"' EXIT
uv run --no-sync python "$final_root/harness.py" run pairs
uv run --no-sync python "$final_root/harness.py" summarize
uv run --no-sync python "$final_root/audit-results.py" \
    --root "$final_root" --live > "$final_root/audit-results.json"
