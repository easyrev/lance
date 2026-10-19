#!/usr/bin/env bash
set -euo pipefail
variant="$1"
run_root=/mnt/lance/unified-9505-20261019
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/${variant}-integration-exit-code"' EXIT
source /mnt/lance/env.sh
source /mnt/lance/proxy.sh
proxy-on >/dev/null
export CARGO_BUILD_JOBS=4
if [[ "$variant" = P ]]; then
    checkout=/mnt/lance/checkouts/unified-9505-P-integration
    export CARGO_TARGET_DIR=/mnt/lance/targets/unified-9505-P-integration
    git -C /mnt/lance/src/lance worktree add --detach "$checkout" 0a0d327082988018a25f56147d3b6d02f6c79ecc
    git -C "$checkout" apply "$run_root/ports/P/implementation.patch"
    cp -a --reflink=auto /mnt/lance/targets/K_noadmission_python "$CARGO_TARGET_DIR"
else
    test "$variant" = DP
    while [[ ! -f "$run_root/logs/DP-rust-exit-code" ]]; do sleep 10; done
    test "$(cat "$run_root/logs/DP-rust-exit-code")" = 0
    checkout=/mnt/lance/checkouts/unified-9505-DP-tests
    export CARGO_TARGET_DIR=/mnt/lance/targets/unified-9505-DP-tests
fi
cd "$checkout"
git diff --binary > "$run_root/logs/${variant}-integration-snapshot.patch"
LANCE_ENABLE_UNSTABLE_DATA_OVERLAY_FILES=1 cargo test -p lance --test merge_insert_memory_bound --profile release-with-debug --locked -- --test-threads=1 > "$run_root/logs/${variant}-integration.log" 2>&1
sha256sum "$CARGO_TARGET_DIR"/release-with-debug/deps/merge_insert_memory_bound-* > "$run_root/logs/${variant}-integration-artifacts.sha256"
date -u --iso-8601=seconds
