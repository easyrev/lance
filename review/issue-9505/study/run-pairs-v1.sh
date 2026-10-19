#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
test "$(cat "$run_root/logs/followup-survival-v1-exit-code")" = 0
test ! -e "$run_root/logs/pairs-v1-exit-code"
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/pairs-v1-exit-code"' EXIT
source /mnt/lance/env.sh
cd /mnt/lance/checkouts/U_main/python
harness="$run_root/harness/harness.py"
uv run --no-sync python "$harness" make-plan --name pairs-f16-v1 --freeze all-v1 --kind pairs --variants B,P,D,DB,DP --workloads F16 --comparisons DB/rewrite_rows:D/rewrite_rows,DP/rewrite_rows:P/rewrite_rows,DB/rewrite_rows:B/rewrite_rows,DB/rewrite_rows:DP/rewrite_rows,D/rewrite_rows:P/rewrite_rows,B/rewrite_rows:P/rewrite_rows
uv run --no-sync python "$harness" run pairs-f16-v1
uv run --no-sync python "$harness" make-plan --name pairs-wn-v1 --freeze all-v1 --kind pairs --variants B,P,D,DB,DP --workloads Wn --comparisons D/rewrite_rows:B/rewrite_rows,D/rewrite_rows:P/rewrite_rows,DB/rewrite_rows:D/rewrite_rows,DP/rewrite_rows:P/rewrite_rows,DB/rewrite_rows:DP/rewrite_rows
uv run --no-sync python "$harness" run pairs-wn-v1
uv run --no-sync python "$harness" make-plan --name pairs-ws-v1 --freeze all-v1 --kind pairs --variants P,D,DB,DP --workloads Ws --comparisons D/rewrite_rows:P/rewrite_rows,DB/rewrite_rows:D/rewrite_rows,DP/rewrite_rows:P/rewrite_rows,DB/rewrite_rows:DP/rewrite_rows
uv run --no-sync python "$harness" run pairs-ws-v1
uv run --no-sync python "$harness" make-plan --name pairs-reverse-v1 --freeze all-v1 --kind pairs --variants B,D,DB --workloads R_admission --pool-mib 256 --comparisons DB/rewrite_rows:D/rewrite_rows,B/rewrite_rows:D/rewrite_rows,DB/rewrite_rows:B/rewrite_rows
uv run --no-sync python "$harness" run pairs-reverse-v1
uv run --no-sync python "$harness" make-plan --name pairs-ordinary-v1 --freeze all-v1 --kind pairs --variants CTX,B,P,D,DB,DP --workloads N_dense,V_dense --comparisons D/rewrite_rows:CTX/rewrite_rows,DB/rewrite_rows:D/rewrite_rows,DB/rewrite_rows:B/rewrite_rows,DP/rewrite_rows:P/rewrite_rows,DB/rewrite_rows:DP/rewrite_rows,P/rewrite_rows:B/rewrite_rows
uv run --no-sync python "$harness" run pairs-ordinary-v1
date -u --iso-8601=seconds
