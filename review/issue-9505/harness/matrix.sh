#!/usr/bin/env bash
set -u
root=/mnt/lance/issue-9505
while ! grep -q 'Exit status: 0' "$root/logs/pr10077-install.log" 2>/dev/null; do
  if grep -q 'Exit status: [1-9]' "$root/logs/pr10077-install.log" 2>/dev/null; then exit 3; fi
  sleep 10
done
while pgrep -x cargo >/dev/null || pgrep -x rustc >/dev/null; do sleep 10; done
(
  cd "$root/pr10077/python" || exit 2
  /root/.local/bin/uv run --no-sync pytest python/tests/test_dataset.py -k merge_insert -q
) > "$root/logs/pr10077-python-tests.log" 2>&1
echo "PR Python regression status=$?"
run() {
  echo "RUN $*"
  "$root/harness/run.sh" "$@" > /dev/null 2>&1
  echo "DONE $1 $2 status=$?"
}
for variant in main fix pr10077; do
  test -f "$root/$variant/python/.venv/pyvenv.cfg" || exit 2
  for repeat in 1 2; do
    for rows in 4000000 16000000 64000000; do
      for source in materialized streaming; do
        run "$variant" "fixed-$rows-$source-$repeat" 64G 1073741824 execute --uri "$root/data/fixed-$rows" --source "$source"
      done
    done
    for source in materialized streaming; do
      run "$variant" "reverse-$source-$repeat" 8G 1073741824 execute --uri "$root/data/reverse" --full-schema --source-rows 3000000 --source "$source"
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
done
