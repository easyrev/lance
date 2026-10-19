#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/hypotheses-9505-20261019
source /mnt/lance/env.sh
test "$(cat "$run_root/logs/pairs-exit-code")" = 0
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/unit-tests-exit-code"' EXIT
cd /mnt/lance/checkouts/hypotheses-9505
unset LANCE_HYPOTHESIS_SPEC
export RUST_TEST_THREADS=1
export TMPDIR="$run_root/unit-test-tmp"
mkdir -p "$TMPDIR"
"$run_root/bin/probe-v1" io::exec::take::tests:: --nocapture
"$run_root/bin/probe-v1" dataset::write::merge_insert::tests::deferred_conditions:: --nocapture
"$run_root/bin/probe-v1" dataset::write::merge_insert::tests::spilled_lineage:: --nocapture
for selected_test in \
  dataset::write::merge_insert::tests::external_error::test_merge_insert_execute_reader_preserves_error_message \
  dataset::write::merge_insert::tests::test_merge_insert_execute_provider \
  dataset::write::merge_insert::tests::test_merge_insert_execute_batches \
  dataset::write::merge_insert::tests::test_merge_insert_execute_batches_empty \
  dataset::write::merge_insert::tests::test_merge_insert_source_statistics_in_plan \
  dataset::write::merge_insert::tests::test_merge_insert_spill_for_retry_false_fails_fast; do
  "$run_root/bin/probe-v1" --exact "$selected_test" --nocapture
done
date -u --iso-8601=seconds
