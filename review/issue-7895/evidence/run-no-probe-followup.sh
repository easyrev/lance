#!/usr/bin/env bash
set -euo pipefail
evidence=/workspace/issue-7895-evidence
mkdir -p "$evidence/no-probe-followup"
for repetition in $(seq 1 10); do
  labels=(baseline candidate)
  if (( repetition % 2 == 0 )); then labels=(candidate baseline); fi
  for label in "${labels[@]}"; do
    trial_id="no-probe-small-lance-$label-$repetition"
    REPLAY_PROBE_DISABLED=1 "$evidence/run-trial.sh" "$trial_id" \
      --package "$evidence/$label-perf-python" --label "no-probe-$label" \
      --root "$evidence/benchmark-fixture-small" --kind lance --trial "$repetition" \
      > "$evidence/no-probe-followup/$trial_id.jsonl" \
      2> "$evidence/no-probe-followup/$trial_id.stderr"
  done
done
