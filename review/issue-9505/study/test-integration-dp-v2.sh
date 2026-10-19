#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/DP-integration-exit-code"' EXIT
for variant in DB DP; do
    while [[ ! -f "$run_root/logs/${variant}-rust-exit-code" ]]; do sleep 10; done
    test "$(cat "$run_root/logs/${variant}-rust-exit-code")" = 0
done
source /mnt/lance/env.sh
source /mnt/lance/proxy.sh
proxy-on >/dev/null
export CARGO_BUILD_JOBS=8
export CARGO_TARGET_DIR=/mnt/lance/targets/unified-9505-DP-tests
cd /mnt/lance/checkouts/unified-9505-DP-tests
git diff --binary > "$run_root/logs/DP-integration-snapshot.patch"
LANCE_ENABLE_UNSTABLE_DATA_OVERLAY_FILES=1 cargo test -p lance --test merge_insert_memory_bound --profile release-with-debug --locked -- --test-threads=1 > "$run_root/logs/DP-integration.log" 2>&1
sha256sum "$CARGO_TARGET_DIR"/release-with-debug/deps/merge_insert_memory_bound-* > "$run_root/logs/DP-integration-artifacts.sha256"
date -u --iso-8601=seconds
