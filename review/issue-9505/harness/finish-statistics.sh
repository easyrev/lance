#!/usr/bin/env bash
set -eu
root=/mnt/lance/issue-9505
while ! test -f "$root/logs/statistics-python-tests.exit"; do sleep 5; done
cd "$root/statistics/python"
. /mnt/lance/env.sh
. /mnt/lance/proxy.sh
proxy-on
export CARGO_TARGET_DIR="$root/target"
uv run --no-sync ruff format python/lance/dataset.py python/tests/test_dataset.py
/usr/bin/time -v uv run --no-sync make -f Makefile -f ../../harness/profile.mk build UV_RUN='uv run --no-sync' > "$root/logs/statistics-build-final.log" 2>&1
uv run --no-sync pytest python/tests/test_dataset.py -k merge_insert -q > "$root/logs/statistics-python-tests-final.log" 2>&1
echo 0 > "$root/logs/statistics-python-tests-final.exit"
uv run --no-sync pytest --doctest-modules python/lance/dataset.py -k 'explain_plan or analyze_plan' -q > "$root/logs/statistics-doctests.log" 2>&1
echo 0 > "$root/logs/statistics-doctests.exit"
export CARGO_TARGET_DIR="$root/target-test"
uv run --no-sync make lint > "$root/logs/statistics-python-lint-final.log" 2>&1
echo 0 > "$root/logs/statistics-python-lint-final.exit"
while ! test -f "$root/logs/statistics-rust-tests-final.exit"; do sleep 5; done
while ! test -f "$root/logs/statistics-clippy.exit"; do sleep 5; done
test "$(cat "$root/logs/statistics-rust-tests-final.exit")" = 0
test "$(cat "$root/logs/statistics-clippy.exit")" = 0
cd "$root/statistics"
cargo fmt --all -- --check
git diff --check
while pgrep -x cargo >/dev/null || pgrep -x rustc >/dev/null; do sleep 5; done
bash "$root/harness/statistics-matrix.sh" > "$root/logs/statistics-matrix.log" 2>&1
bash "$root/harness/boundary-matrix.sh" > "$root/logs/boundary-matrix.log" 2>&1
