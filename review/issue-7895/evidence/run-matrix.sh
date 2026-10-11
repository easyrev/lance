#!/usr/bin/env bash
set -euo pipefail
evidence=/workspace/issue-7895-evidence
baseline_package=$1
candidate_package=$2
fixture=$3
fixture_name=$(basename "$fixture")
repetitions=${4:-5}
mkdir -p "$evidence/raw"

# Alternate which binary runs first to limit temporal bias from cache and load.
for repetition in $(seq 1 "$repetitions"); do
  if (( repetition % 2 == 1 )); then
    labels=(baseline candidate)
  else
    labels=(candidate baseline)
  fi
  for kind in lance arrow scanner; do
    for conflict in clean conflict; do
      options=()
      if [[ "$conflict" == conflict ]]; then options+=(--conflict); fi
      for label in "${labels[@]}"; do
        package="$candidate_package"
        if [[ "$label" == baseline ]]; then package="$baseline_package"; fi
        trial_id="$fixture_name-$label-$kind-$conflict-$repetition"
        "$evidence/run-trial.sh" "$trial_id" \
          --label "$label" --package "$package" --root "$fixture" \
          --kind "$kind" --trial "$repetition" "${options[@]}" \
          >"$evidence/raw/$trial_id.jsonl" 2>"$evidence/raw/$trial_id.stderr"
      done
    done
  done
done
