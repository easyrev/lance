#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/first-wave-exit-code"' EXIT
source /mnt/lance/env.sh
for marker in build-rest-complete test-rest-complete test-python-rest-complete; do
    test -f "$run_root/logs/$marker"
done
for variant in B P CTX DB DP; do
    test "$(cat "$run_root/logs/$variant-build-exit-code")" = 0
done
for variant in U B P D CTX DB DP; do
    test "$(cat "$run_root/logs/$variant-python-exit-code")" = 0
done
for variant in DB DP; do
    test "$(cat "$run_root/logs/$variant-rust-exit-code")" = 0
done
for variant in P DP; do
    test "$(cat "$run_root/logs/$variant-integration-exit-code")" = 0
done
cd /mnt/lance/checkouts/U_main/python
harness="$run_root/harness/harness.py"
uv run --no-sync python "$harness" freeze --name all-v1 --variants U,B,P,D,CTX,DB,DP
uv run --no-sync python "$harness" make-plan --name correctness-all-v1 --freeze all-v1 --kind correctness --variants U,B,P,D,CTX,DB,DP
uv run --no-sync python "$harness" run correctness-all-v1
uv run --no-sync python "$harness" make-plan --name survival-main-v1 --freeze all-v1 --kind survival --variants U,B,P,D,CTX,DB,DP --workloads F16,Wn,Ws
uv run --no-sync python "$harness" run survival-main-v1
uv run --no-sync python "$harness" make-plan --name survival-reverse-v1 --freeze all-v1 --kind survival --variants U,B,P,D,CTX,DB,DP --workloads R_admission --pool-mib 256
uv run --no-sync python "$harness" run survival-reverse-v1
uv run --no-sync python "$harness" make-plan --name survival-ordinary-v1 --freeze all-v1 --kind survival --variants CTX,D --workloads N_dense,V_dense,late_jump
uv run --no-sync python "$harness" run survival-ordinary-v1
uv run --no-sync python "$harness" make-plan --name survival-growth-v1 --freeze all-v1 --kind survival --variants D,DB --workloads F64
uv run --no-sync python "$harness" run survival-growth-v1
date -u --iso-8601=seconds
