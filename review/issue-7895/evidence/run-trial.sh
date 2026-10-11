#!/usr/bin/env bash
set -euo pipefail
source /workspace/issue-7895-evidence/env.sh
evidence=/workspace/issue-7895-evidence
trial_id=$1
shift
probe_dir="$evidence/probes/$trial_id"
mkdir -p "$probe_dir/tmp"
export TMPDIR="$probe_dir/tmp"
export REPLAY_PROBE_ROOT="$TMPDIR"
export REPLAY_PROBE_LOG="$probe_dir/events.tsv"
if [[ "${REPLAY_PROBE_DISABLED:-0}" == 1 ]]; then
  unset LD_PRELOAD
else
  export LD_PRELOAD="$evidence/replay_probe.so"
fi
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export RAYON_NUM_THREADS=4
export TOKIO_WORKER_THREADS=4
cd /workspace/lance-7895/python
uv run --no-sync python "$evidence/benchmark.py" "$@"
