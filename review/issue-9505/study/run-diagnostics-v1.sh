#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
test ! -e "$run_root/logs/diagnostics-v1-exit-code"
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/diagnostics-v1-exit-code"' EXIT
while test ! -f "$run_root/logs/pairs-v1-exit-code"; do sleep 30; done
test "$(cat "$run_root/logs/pairs-v1-exit-code")" = 0
source /mnt/lance/env.sh
cd /mnt/lance/checkouts/U_main/python
harness="$run_root/harness/harness.py"
uv run --no-sync python "$harness" make-plan --name diagnose-f16-v1 --freeze all-v1 --kind diagnose --variants B,P,D,DB,DP --workloads F16
uv run --no-sync python "$harness" run diagnose-f16-v1
uv run --no-sync python "$harness" make-plan --name diagnose-ws-v1 --freeze all-v1 --kind diagnose --variants P,D,DB,DP --workloads Ws
uv run --no-sync python "$harness" run diagnose-ws-v1
uv run --no-sync python "$harness" make-plan --name diagnose-wn-v1 --freeze all-v1 --kind diagnose --variants D,DP --workloads Wn
uv run --no-sync python "$harness" run diagnose-wn-v1
uv run --no-sync python "$harness" make-plan --name diagnose-ordinary-v1 --freeze all-v1 --kind diagnose --variants CTX,B,P,D,DB,DP --workloads N_dense,V_dense
uv run --no-sync python "$harness" run diagnose-ordinary-v1
date -u --iso-8601=seconds
