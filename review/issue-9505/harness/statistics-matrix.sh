#!/usr/bin/env bash
set -u
root=/mnt/lance/issue-9505
run() {
  echo "RUN $*"
  "$root/harness/run.sh" "$@" > /dev/null 2>&1
  echo "DONE $1 $2 status=$?"
}
variant=statistics
for repeat in 1 2; do
  for rows in 4000000 16000000 64000000; do
    for source in materialized streaming; do
      run "$variant" "fixed-$rows-$source-$repeat" 64G 1073741824 execute --uri "$root/data/fixed-$rows" --source "$source"
    done
  done
  for source in materialized streaming; do
    run "$variant" "reverse-$source-$repeat" 8G 1073741824 execute --uri "$root/data/reverse" --full-schema --source-rows 3000000 --source "$source"
    run "$variant" "reverse-highmem-$source-$repeat" 16G 8589934592 execute --uri "$root/data/reverse" --full-schema --source-rows 3000000 --source "$source"
    run "$variant" "wide-$source-$repeat" 8G 1073741824 execute --uri "$root/data/wide" --source-rows 25 --source-binary-bytes 10485760 --source "$source"
  done
  run "$variant" "limited-$repeat" 2G 268435456 execute --uri "$root/data/fixed-4000000" --source streaming
done
run "$variant" "wide-limited" 2G 1073741824 execute --uri "$root/data/wide" --source-rows 25 --source-binary-bytes 10485760 --source streaming
for source in materialized streaming; do
  run "$variant" "plan-fixed-$source" 16G 1073741824 analyze --uri "$root/data/fixed-4000000" --source "$source"
  run "$variant" "plan-reverse-$source" 8G 1073741824 analyze --uri "$root/data/reverse" --full-schema --source-rows 3000000 --source "$source"
  run "$variant" "plan-wide-$source" 8G 1073741824 analyze --uri "$root/data/wide" --source-rows 25 --source-binary-bytes 10485760 --source "$source"
done
for variant in main fix pr10077 statistics; do
  for repeat in 1 2; do
    for source in materialized streaming; do
      run "$variant" "wide-small-source-$source-$repeat" 8G 1073741824 execute --uri "$root/data/wide" --source-rows 25 --source "$source"
    done
  done
  run "$variant" "wide-small-source-limited" 2G 1073741824 execute --uri "$root/data/wide" --source-rows 25 --source streaming
  run "$variant" "plan-wide-small-source" 8G 1073741824 analyze --uri "$root/data/wide" --source-rows 25 --source streaming
done
