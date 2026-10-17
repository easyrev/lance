#!/usr/bin/env bash
set -u
root=/mnt/lance/issue-9505
for variant in main fix pr10077 statistics; do
  for repeat in 1 2; do
    for source in materialized streaming; do
      run_id="source-100k-$source-$repeat"
      "$root/harness/run.sh" "$variant" "$run_id" 8G 1073741824 execute \
        --uri "$root/data/fixed-4000000" --source-rows 100000 --source "$source" > /dev/null 2>&1
      echo "$variant $run_id status=$?"
    done
  done
  "$root/harness/run.sh" "$variant" plan-source-100k-streaming 8G 1073741824 analyze \
    --uri "$root/data/fixed-4000000" --source-rows 100000 --source streaming > /dev/null 2>&1
  echo "$variant plan-source-100k-streaming status=$?"
done
