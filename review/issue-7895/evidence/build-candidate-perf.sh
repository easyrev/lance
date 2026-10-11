#!/usr/bin/env bash
set -euo pipefail
source /workspace/issue-7895-evidence/env.sh
cd /workspace/lance-7895
export CARGO_TARGET_DIR=/workspace/issue-7895-perf-target
export CARGO_BUILD_JOBS=3
export PYO3_PYTHON=/workspace/lance-7895/python/.venv/bin/python
unset PYO3_ENVIRONMENT_SIGNATURE
cc_path=/workspace/.cargo/bin/cc
[[ ! -e "$cc_path" && ! -L "$cc_path" ]]
ln -s /workspace/issue-7895-evidence/perf-cc-wrapper.sh "$cc_path"
trap 'rm -f /workspace/.cargo/bin/cc' EXIT
cargo build --locked --profile release-with-debug --manifest-path python/Cargo.toml
/workspace/issue-7895-evidence/snapshot-performance.sh candidate-perf \
 /workspace/lance-7895/python/python \
 /workspace/issue-7895-perf-target/release-with-debug/liblance.so \
 /workspace/issue-7895-evidence/candidate-perf-python
