#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'status=$?; echo "$status" > "$raw/diagnostic.exit"' EXIT
space
[[ $(cat "$raw/measure.exit") == 0 && -s "$disk/reports/diagnostic-cases.tsv" ]]
mkdir -p "$raw/diagnostic"

head=$(cat "$raw/commit-head.txt")
git -C "$disk/head" worktree add --detach "$disk/diagnostic" "$head"
python3 "$disk/scripts/instrument.py" "$disk/diagnostic"
git -C "$disk/diagnostic" diff > "$raw/diagnostic/instrumentation.patch"

resolve diagnostic
export CARGO_TARGET_DIR="$task/diagnostic-target" UV_PROJECT_ENVIRONMENT="$environment"
needed=$(( $(du -s -B1 "$disk/target-head" | cut -f 1) + 10737418240 ))
available=$(df -B1 --output=avail /dev/shm | tail -1)
if (( available < needed )); then
    sha256sum -c "$raw/extension-base.sha256"
    test "$(readlink "$disk/target-base")" = "$task/target-base"
    rm -rf --one-file-system -- "$task/target-base"
    unlink "$disk/target-base"
    printf 'Cleared completed rerun base Cargo cache at %s after formal timing.\n' "$task/target-base"
fi
mkdir "$CARGO_TARGET_DIR"
cp -a "$disk/target-head/." "$CARGO_TARGET_DIR/"
space
export MATURIN_PEP517_ARGS='--profile release-with-debug' CARGO_BUILD_JOBS=24
export RUSTC_WRAPPER=""
(
    cd "$checkout/python"
    make install PYTHON=3.12 UV_SYNC='uv sync --frozen --python 3.12 --no-install-project --verbose'
    make build BUILD_SHELL="$tools/reused/build-shell" UV_RUN='uv run --frozen --no-sync' \
        --eval='build: override SHELL := $(BUILD_SHELL)'
) > "$raw/diagnostic/build.log" 2>&1
sha256sum "$extension" > "$raw/diagnostic/extension.sha256"
sha256sum -c "$raw/extension-head.sha256" "$raw/extension-base.sha256" > "$raw/diagnostic/formal-extensions-unchanged.txt"

while IFS=$'\t' read -r dataset op; do
    space
    for i in "${!datasets[@]}"; do
        if [[ ${datasets[$i]} == "$dataset" ]]; then rows=${row_counts[$i]}; break; fi
    done
    path=$task/p1/$dataset
    if [[ $op == scan ]]; then
        args=("$tools/scan.py" "$path" "$rows")
    else
        args=("$tools/take.py" "$path" "${op#repeat}" --dataset-rows "$rows" --take-only --repeat 20)
    fi
    run diagnostic "${args[@]}" > "$raw/diagnostic/$dataset-$op.jsonl" 2> "$raw/diagnostic/$dataset-$op.log"
done < "$disk/reports/diagnostic-cases.tsv"
python3 "$disk/scripts/diagnostic-report.py" "$disk" > "$disk/reports/diagnostic.md"
python3 "$disk/scripts/deliver.py" "$disk"
