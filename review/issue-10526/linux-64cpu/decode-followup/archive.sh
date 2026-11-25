#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
space
for job in phase1 prepare-phase2 build-exp-A measure-base measure-final measure-exp-A build-exp-B measure-exp-B; do
    test "$(cat "$work/$job.exit")" = 0
done
for check in test-exp-A test-exp-B clippy-exp-B; do
    test "$(cat "$raw/$check.exit")" = 0
done

# Keep raw trials and check logs. The verbose dependency install log is local scratch.
mkdir -p "$scripts/raw"
for pattern in '*.json' '*.jsonl' '*.txt' '*.sha256' '*.exit' '*.log'; do
    while IFS= read -r -d '' file; do
        cp -- "$file" "$scripts/raw/"
    done < <(find "$raw" -maxdepth 1 -type f -name "$pattern" ! -name 'install-*.log' -print0)
done
cp -- "$work"/*.exit "$scripts/raw/"
for job in phase1 prepare-phase2 measure-round-A prep-B bridge-B run-B; do
    if [[ -f $work/$job.log ]]; then
        cp -- "$work/$job.log" "$scripts/raw/"
    fi
done
run final "$scripts/summarize.py" "$scripts/raw" "$scripts/raw/summary.json" \
    > "$work/decode-followup.generated.md"
cp -- "$work/decode-followup.generated.md" "$scripts/../decode-followup.md"
(
    cd "$scripts"
    find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
    sha256sum -c --quiet SHA256SUMS
)
