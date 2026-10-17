#!/usr/bin/env bash
set -euo pipefail
source /workspace/issue-7895-evidence/env.sh
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export RAYON_NUM_THREADS=4
export TOKIO_WORKER_THREADS=4
cd /workspace/lance-7895/python
uv run --no-sync python /workspace/issue-7895-evidence/capture-plans.py "$@"
