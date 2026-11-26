#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
scripts=$(realpath "$(dirname "$0")")
raw=$task/raw
trap 'status=$?; echo "$status" > "$raw/build-var-job.exit"' EXIT
df -h / /dev/shm | tee -a "$raw/space.log"
for mount in / /dev/shm; do (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 )); done
commit=$(git -C /root/lance/shared-buffer-var rev-parse HEAD)
git -C /root/lance/repo worktree add --detach "$task/checkout-var" "$commit"
cd "$task/checkout-var"
export LANCE_CPU_THREADS=64 TMPDIR="$task/tmp" CARGO_TARGET_DIR="$task/target-var" CARGO_BUILD_JOBS=20
set +e
cargo test -q -p lance-encoding --profile release-with-debug > "$raw/test-var.log" 2>&1
status=$?
set -e
echo "$status" > "$raw/test-var.exit"
(( status == 0 ))
bash "$scripts/build.sh" var "$task/checkout-var"
