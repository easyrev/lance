#!/usr/bin/env bash
set -euo pipefail

source /workspace/issue-7895-evidence/env.sh
export CARGO_BUILD_JOBS=2
export CARGO_TARGET_DIR=/workspace/issue-7895-root-target
cd /workspace/lance-7895
printf '%s\n' "$$" > /workspace/issue-7895-evidence/root-rust-validation.pid

case "${1:?Usage: run-root-rust-validation.sh test|clippy}" in
  test)
    cargo test --profile ci --locked -p lance-datafusion --lib \
      test_analyze_plan_uses_provided_task_context \
      > /workspace/issue-7895-evidence/root-core-tests.log 2>&1
    ;;
  clippy)
    cargo clippy --profile ci --locked --all --tests --benches -- -D warnings \
      > /workspace/issue-7895-evidence/root-workspace-clippy.log 2>&1
    ;;
  *)
    printf 'Unknown validation mode: %s\n' "$1" >&2
    exit 2
    ;;
esac
