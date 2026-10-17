#!/usr/bin/env bash
set -eu
root=/mnt/lance/issue-9505
cd "$root/main/python"
uv run --no-sync python "$root/harness/harness.py" generate \
  --uri "$root/data/wide-variable" --rows 2000000 --columns 3 \
  --binary-bytes 2048 --binary-min-bytes 128 --batch-rows 8192 \
  --fragment-rows 100000 --output "$root/results/gen-wide-variable.json"
set +e
for variant in main fix pr10077 statistics; do
  for repeat in 1 2; do
    for source in materialized streaming; do
      "$root/harness/run.sh" "$variant" "wide-variable-$source-$repeat" 16G 1073741824 execute \
        --uri "$root/data/wide-variable" --source "$source" > /dev/null 2>&1
      echo "$variant wide-variable-$source-$repeat status=$?"
    done
  done
  "$root/harness/run.sh" "$variant" plan-wide-variable-streaming 16G 1073741824 analyze \
    --uri "$root/data/wide-variable" --source streaming > /dev/null 2>&1
  echo "$variant plan-wide-variable-streaming status=$?"
done

