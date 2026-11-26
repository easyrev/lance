#!/usr/bin/env bash
set -euo pipefail
scripts=$(realpath "$(dirname "$0")")
disk=/root/lance/tmp/shared-buffer-build
task=/dev/shm/lance-10526/shared-buffer
raw=$disk/raw
selected=$1
trap 'status=$?; echo "$status" > "$raw/final-checks.exit"' EXIT
[[ $(cat "$task/raw/phase2-complete.exit") == 0 ]]
df -h / /dev/shm | tee "$raw/final-checks-space.log"
for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
cargo clean --manifest-path /root/lance/shared-buffer-final/python/Cargo.toml --target-dir "$disk/target-final-b" > "$raw/clean-final-b-target.log" 2>&1
sha256sum -c "$raw/extension-final-b.sha256" >> "$raw/clean-final-b-target.log"
bash "$scripts/code-checks-disk.sh" "$selected" >> "$raw/final-checks-space.log"
if [[ $(cat "$raw/check-clippy-workspace-$selected.exit") != 0 ]]; then
    cargo clean --manifest-path "/root/lance/shared-buffer-$selected/Cargo.toml" --target-dir "$disk/target-$selected" > "$raw/clean-check-target.log" 2>&1
    df -h / /dev/shm >> "$raw/final-checks-space.log"
    for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
    mkdir -p "$disk/tmp-base-clippy"
    export CARGO_TARGET_DIR="$disk/target-base-clippy" TMPDIR="$disk/tmp-base-clippy"
    export RUSTC_WRAPPER="" CARGO_BUILD_JOBS=20 LANCE_CPU_THREADS=64
    cd /root/lance/base
    status=0
    cargo clippy --all --tests --benches --profile release-with-debug -- -D warnings > "$raw/check-clippy-workspace-base.log" 2>&1 || status=$?
    echo "$status" > "$raw/check-clippy-workspace-base.exit"
fi
