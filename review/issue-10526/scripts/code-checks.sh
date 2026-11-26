#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
raw=$task/raw
variant=$1
case $variant in
    pure) cd /root/lance/shared-buffer-pure ;;
    var) cd "$task/checkout-var" ;;
esac
export LANCE_CPU_THREADS=64 CARGO_TARGET_DIR="$task/target-$variant" TMPDIR="$task/tmp" CARGO_BUILD_JOBS=20
df -h / /dev/shm | tee -a "$raw/space.log"
for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
check() {
    local name=$1 status=0
    shift
    "$@" > "$raw/check-$name-$variant.log" 2>&1 || status=$?
    echo "$status" > "$raw/check-$name-$variant.exit"
}
check fmt cargo fmt --all -- --check
check tests cargo test -q -p lance-encoding -p lance-file --profile release-with-debug
check clippy-encoding cargo clippy -p lance-encoding --tests --profile release-with-debug -- -D warnings
check clippy-workspace cargo clippy --all --tests --benches --profile release-with-debug -- -D warnings
