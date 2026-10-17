#!/usr/bin/env bash
set -euo pipefail

# Install only on demand as /workspace/.cargo/bin/cc, then remove afterward.
# Scope the debug representation change to this task's final pylance cdylib.
perf_output=/workspace/issue-7895-perf-target/release-with-debug/deps/liblance.so
link_output=
previous=
for argument in "$@"; do
    if [[ "$previous" == -o ]]; then
        link_output=$argument
    fi
    previous=$argument
done

if [[ "$link_output" == "$perf_output" ]]; then
    {
        printf 'time=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf 'output=%s\n' "$link_output"
        printf 'command='
        printf '%q ' /usr/bin/cc "$@" -Wl,--compress-debug-sections=zstd
        printf '\n'
    } >> /workspace/issue-7895-evidence/perf-linker-compression.log
    exec /usr/bin/cc "$@" -Wl,--compress-debug-sections=zstd
fi

exec /usr/bin/cc "$@"
