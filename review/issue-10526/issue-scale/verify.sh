#!/usr/bin/env bash
set -uo pipefail
evidence=$(cd "$(dirname "$0")" && pwd)
export CARGO_BUILD_JOBS=4
repo=$(git rev-parse --show-toplevel)
cd "$repo"
failed=0
run() {
    local label=$1 rc=0
    shift
    printf '%s %s\n' "$(date -u +%FT%TZ)" "$label"
    "$@" > "$evidence/$label.log" 2>&1 || rc=$?
    echo "$rc" > "$evidence/$label.exit"
    if [ "$rc" -ne 0 ]; then failed=1; fi
    printf '%s exit %s\n' "$label" "$rc"
    return "$rc"
}
run fmt cargo fmt --all
run fmt-check cargo fmt --all -- --check
run rust-tests cargo test -q -p lance-encoding -p lance-file --profile release-no-lto
run benchmark bash "$evidence/benchmark.sh"
run rust-clippy rtk cargo clippy --all --tests --benches -- -D warnings
cd "$repo/python"
run python-install make install
if [ "$(cat "$evidence/python-install.exit")" -eq 0 ]; then
    if run python-build make build; then
        run python-test-file uv run pytest python/tests/test_file.py
    fi
    run python-lint uv run make lint
fi
exit "$failed"
