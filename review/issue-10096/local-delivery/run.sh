#!/usr/bin/env bash
set -euo pipefail
export LANCE_WORKTREE=issue10096
phase=${1:?Specify a phase}
result=/mnt/lance/results/issue10096/$phase
mkdir -p "$result"
exec > >(tee "$result/output.log") 2>&1
trap 'code=$?; printf "%s\n" "$code" > "$result/exit.code"' EXIT
exec 9>/mnt/lance/locks/worktree-$LANCE_WORKTREE.lock
flock -x 9
exec 8>/mnt/lance/locks/heavy.lock
flock -x 8
source /mnt/lance/tools/env.sh
cp /mnt/lance/state/$LANCE_WORKTREE/{revision,working.diff,verified} "$result/"
git status --short > "$result/status.txt"
tar --exclude=.git --exclude=.venv --exclude=target --exclude=__pycache__ --exclude=.pytest_cache -czf "$result/source.tar.gz" .
{ rustc -Vv; cargo -V; uname -a; lscpu; } > "$result/tools.txt"
ps -eo pid,ppid,pcpu,pmem,comm,args --sort=-pcpu > "$result/processes.txt"
case "$phase" in
    baseline-regression|baseline-proof*)
        sccache --stop-server || true
        sccache --start-server
        command=(cargo test --locked -p lance --lib --no-default-features --features tokio/test-util test_staged_index_commits_past_a_deferred_compaction -- --nocapture)
        ;;
    baseline-build*|fixed-build*)
        command=(cargo build --locked -p lance --no-default-features --profile release-with-debug --example staged_coverage_bench)
        ;;
    baseline-lint*|fixed-lint*)
        command=(cargo clippy --all --tests --benches -- -D warnings)
        ;;
    fixed-tests*)
        command=(cargo test --locked -p lance --lib --no-default-features --features tokio/test-util dataset::optimize::tests::concurrent_reindex -- --nocapture)
        ;;
    index-tests*)
        command=(cargo test --locked -p lance --lib --no-default-features --features tokio/test-util index:: -- --test-threads=4)
        ;;
    resolver-tests*)
        command=(cargo test --locked -p lance --lib --no-default-features --features tokio/test-util io::commit::conflict_resolver -- --test-threads=4)
        ;;
    example-lint-default*)
        command=(cargo clippy --locked -p lance --example staged_coverage_bench -- -D warnings -A clippy::print_stderr)
        ;;
    example-lint*)
        command=(cargo clippy --locked -p lance --no-default-features --example staged_coverage_bench -- -D warnings)
        ;;
    *) exit 2 ;;
esac
printf '%q ' "${command[@]}" > "$result/command.txt"
printf '\n' >> "$result/command.txt"
"${command[@]}"
if [[ $phase == *-build* ]]; then
    cp "$CARGO_TARGET_DIR/release-with-debug/examples/staged_coverage_bench" "$result/bench"
fi
