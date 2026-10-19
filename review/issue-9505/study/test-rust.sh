#!/usr/bin/env bash
set -euo pipefail
variant="$1"
run_root=/mnt/lance/unified-9505-20261019
checkout="/mnt/lance/checkouts/unified-9505-${variant}-tests"
target="/mnt/lance/targets/unified-9505-${variant}-tests"
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/${variant}-rust-exit-code"' EXIT
source /mnt/lance/env.sh
source /mnt/lance/proxy.sh
proxy-on >/dev/null
export CARGO_TARGET_DIR="$target"
export CARGO_BUILD_JOBS=6
git -C /mnt/lance/src/lance worktree add --detach "$checkout" 0a0d327082988018a25f56147d3b6d02f6c79ecc
git -C "$checkout" apply "$run_root/ports/$variant/implementation.patch"
git -C "$checkout" apply "$run_root/tests/late-jump.patch"
git -C "$checkout" diff --binary > "$run_root/logs/${variant}-test-snapshot.patch"
cp -a --reflink=auto /mnt/lance/targets/K_noadmission_python "$target"
cd "$checkout"
cargo fmt --all -- --check > "$run_root/logs/${variant}-fmt.log" 2>&1
LANCE_ENABLE_UNSTABLE_DATA_OVERLAY_FILES=1 cargo test -p lance --lib dataset::write::merge_insert --profile release-with-debug --locked -- --test-threads=4 > "$run_root/logs/${variant}-rust-tests.log" 2>&1
sha256sum "$target"/release-with-debug/deps/lance-* > "$run_root/logs/${variant}-rust-artifacts.sha256"
date -u --iso-8601=seconds
