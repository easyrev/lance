#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
test "$(cat "$run_root/logs/first-wave-exit-code")" = 0
test ! -e "$run_root/logs/followup-survival-v1-exit-code"
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/followup-survival-v1-exit-code"' EXIT
source /mnt/lance/env.sh
bash "$run_root/capture-dependencies.sh"
cd /mnt/lance/checkouts/U_main/python
harness="$run_root/harness/harness.py"
uv run --no-sync python "$harness" make-plan --name survival-ordinary-controls-v1 --freeze all-v1 --kind survival --variants B,P,DB,DP --workloads N_dense,V_dense
uv run --no-sync python "$harness" run survival-ordinary-controls-v1
uv run --no-sync python "$harness" make-plan --name cold-ordinary-v1 --freeze all-v1 --kind cold --variants CTX,D --workloads V_dense --cache evict_attempt
uv run --no-sync python "$harness" run cold-ordinary-v1
date -u --iso-8601=seconds
