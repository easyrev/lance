#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
test ! -e "$run_root/logs/audit-final-v1-exit-code"
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/audit-final-v1-exit-code"' EXIT
while test ! -f "$run_root/logs/diagnostics-v1-exit-code"; do sleep 30; done
test "$(cat "$run_root/logs/diagnostics-v1-exit-code")" = 0
source /mnt/lance/env.sh
cd /mnt/lance/checkouts/U_main/python
uv run --no-sync python "$run_root/harness/harness.py" summarize
uv run --no-sync python "$run_root/audit-results.py" --root "$run_root" --verify-files --output "$run_root/audit-final-v1.json"
date -u --iso-8601=seconds
