#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'status=$?; echo "$status" > "$raw/target-base-relocation.exit"' EXIT
space
target=$task/target-base
mkdir -p "$task"
test -d "$disk/target-base" && test ! -e "$target"
date -u +%FT%TZ
du -sh "$disk/target-base"
df -h / /dev/shm
sha256sum -c "$raw/extension-base.sha256"
mv -- "$disk/target-base" "$target"
ln -s "$target" "$disk/target-base"
printf 'Moved completed base Cargo target from %s to %s\n' "$disk/target-base" "$target"
sha256sum -c "$raw/extension-base.sha256"
df -h / /dev/shm
