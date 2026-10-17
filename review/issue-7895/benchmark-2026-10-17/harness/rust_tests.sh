#!/usr/bin/env bash
# Post-rebase Rust tests touched by the PR, in a dedicated debug target dir.
set -uo pipefail
source /mnt/lance/env.sh
source /mnt/lance/proxy.sh
proxy-on
export CARGO_TARGET_DIR=/mnt/lance/target-test
cd /mnt/lance/bench-9617/src-pr
echo "== lance-datafusion"; cargo test -p lance-datafusion --lib 2>&1 | tail -6; echo "exit=${PIPESTATUS[0]}"
echo "== lance merge_insert"; cargo test -p lance --lib dataset::write::merge_insert 2>&1 | tail -6; echo "exit=${PIPESTATUS[0]}"
cd python
echo "== pylance replayable"; cargo test --no-default-features --lib replayable 2>&1 | tail -12; echo "exit=${PIPESTATUS[0]}"
echo rust-tests-done
