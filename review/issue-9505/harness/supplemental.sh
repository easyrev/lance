#!/usr/bin/env bash
set -u
root=/mnt/lance/issue-9505
matrix_pid=${1:?Pass the running matrix PID}
while kill -0 "$matrix_pid" 2>/dev/null; do sleep 5; done
mkdir -p "$root/results/validation-errors"
for source in materialized streaming; do
  mv "$root/results/main/wide-$source-1."* "$root/results/validation-errors/"
  "$root/harness/run.sh" main "wide-$source-1" 8G 1073741824 execute --uri "$root/data/wide" --source-rows 25 --source-binary-bytes 10485760 --source "$source" > /dev/null 2>&1
  echo "Wide validation rerun $source status=$?"
done
for variant in main fix pr10077; do
  for repeat in 1 2; do
    for source in materialized streaming; do
      "$root/harness/run.sh" "$variant" "reverse-highmem-$source-$repeat" 16G 8589934592 execute --uri "$root/data/reverse" --full-schema --source-rows 3000000 --source "$source" > /dev/null 2>&1
      echo "$variant reverse-highmem-$source-$repeat status=$?"
    done
  done
done
