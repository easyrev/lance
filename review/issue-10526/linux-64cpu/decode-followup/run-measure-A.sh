#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'echo $? > "$work/measure-round-A.exit"' EXIT
while tmux has-session -t '=lance-10526-build-A' 2>/dev/null ||
      tmux has-session -t '=lance-10526-test-A' 2>/dev/null; do
    sleep 10
done
space
test "$(cat "$work/build-exp-A.exit")" = 0
test "$(cat "$raw/test-exp-A.exit")" = 0
test "$(cat "$work/prepare-phase2.exit")" = 0
test "$(git -C "$root/exp-decode" rev-parse HEAD)" = "$(cat "$raw/test-exp-A-commit.txt")"
git -C "$root/exp-decode" diff --exit-code HEAD --
cp "$raw/commit-exp-A.txt" "$raw/commit-exp-A-initial.txt"
cp "$raw/test-exp-A-commit.txt" "$raw/commit-exp-A.txt"
for variant in base final exp-A; do
    bash "$scripts/measure-phase2.sh" "$variant"
done
