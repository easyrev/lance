#!/usr/bin/env bash
set -euo pipefail
scripts=$(realpath "$(dirname "$0")")
task=/dev/shm/lance-10526/shared-buffer
disk=/root/lance/tmp/shared-buffer-build
mkdir -p "$disk/raw"
trap 'status=$?; echo "$status" > "$disk/raw/resume-serial.exit"' EXIT
for mode in pure var; do
    checkout=/root/lance/shared-buffer-$mode
    bash "$scripts/build-disk.sh" "$mode" "$checkout"
    # The installed native module remains in its own checkout on disk. Free this
    # candidate's generated Cargo cache before beginning the next build.
    cargo clean --manifest-path "$checkout/python/Cargo.toml" --target-dir "$disk/target-$mode" > "$disk/raw/clean-$mode-target.log" 2>&1
    sha256sum -c "$disk/raw/extension-$mode.sha256" >> "$disk/raw/clean-$mode-target.log"
done
bash "$scripts/phase1-resume.sh" > "$task/raw/phase1-resume.log" 2>&1
