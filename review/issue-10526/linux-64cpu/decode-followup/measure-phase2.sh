#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'echo $? > "$work/measure-$1.exit"' EXIT
variant=$1
space
test "$(cat "$work/prepare-phase2.exit")" = 0
if [[ $variant == base || $variant == final ]]; then
    build=$variant
    dataset_variant=$variant
else
    test "$(cat "$work/build-$variant.exit")" = 0
    build=exp-decode
    dataset_variant=final
    export UV_PROJECT_ENVIRONMENT=$work/venv-exp
    test "$(git -C "$root/$build" rev-parse HEAD)" = "$(cat "$raw/commit-$variant.txt")"
    sha256sum -c "$raw/extension-$variant.sha256"
    for kind in wide-unique wide-unique-8k wide-mixed; do
        space
        name=$dataset_variant-$kind
        if [[ $kind == wide-unique ]]; then name=$dataset_variant-default; fi
        pages=$(jq -r .pages "$raw/pages-$name.json")
        run "$build" "$scripts/inspect_data.py" "$data/$name" "$pages" \
            > "$raw/pages-$name-$variant.json"
        cmp "$raw/pages-$name.json" "$raw/pages-$name-$variant.json"
        run "$build" "$scripts/verify.py" "$data/$name" "$original/ipc/$kind.arrow" \
            > "$raw/verify-$kind-$variant.json"
    done
    for count in 128 1024; do
        for trial in 1 2 3; do
            space
            run "$build" "$scripts/take.py" "$data/final-default" "$count" \
                --take-only --repeat 20 > "$raw/repeat-$count-$trial-$variant.jsonl"
        done
    done
fi
for kind in wide-unique-8k wide-unique; do
    name=$dataset_variant-$kind
    if [[ $kind == wide-unique ]]; then name=$dataset_variant-default; fi
    for operation in scan take; do
        if [[ $kind == wide-unique && $operation == take ]]; then continue; fi
        for trial in 1 2 3; do
            space
            run "$build" "$bench" read "$data/$name" "$original/ipc/$kind.arrow" "$operation" \
                > "$raw/$operation-$kind-$trial-$variant.json"
        done
    done
done
