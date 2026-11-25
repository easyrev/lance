#!/bin/bash
set -euo pipefail
root=/root/lance
work=/dev/shm/lance-10526
out=$work/take-investigation
scripts=$root/tmp/take10526
bench=$root/tmp/10526-review/review/issue-10526/linux-64cpu/bench.py
mkdir -p "$out/raw" "$out/data"
trap 'echo $? > "$out/exit"' EXIT
space() {
    df -h / /dev/shm >> "$out/raw/space.log"
    for mount in / /dev/shm; do
        (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 ))
    done
}
run() (
    local version=$1
    shift
    cd "$root/$version/python"
    export UV_CACHE_DIR="$root/cache/uv" LANCE_CPU_THREADS=64 LANCE_BENCH_PROTO_DIR="$root/$version/protos"
    exec uv run --frozen --no-sync python -B "$@"
)
for name in base-default final-default final-1 final-2 final-8 final-44 final-135; do
    space
    version=${name%%-*}
    pages=${name#*-}
    unset LANCE_FILE_WRITER_MAX_PAGE_BYTES
    if [[ $pages != default ]]; then
        export LANCE_FILE_WRITER_MAX_PAGE_BYTES=$(( ((25000+pages-1)/pages)*180000 ))
    fi
    echo "$name ${LANCE_FILE_WRITER_MAX_PAGE_BYTES:-default}" >> "$out/raw/page-budgets.txt"
    run "$version" "$bench" measure "$work/ipc/wide-unique.arrow" "$out/data" --writers 1 --file-stats --keep "$out/data/$name" > "$out/raw/file-$name.json"
    if [[ $pages != default ]]; then
        run "$version" -c 'import json,sys; assert json.load(open(sys.argv[1]))["pages"] == int(sys.argv[2])' "$out/raw/file-$name.json" "$pages"
    fi
done
unset LANCE_FILE_WRITER_MAX_PAGE_BYTES
for count in 1 16 128 1024; do
    for trial in {1..5}; do
        for version in base final; do
            space
            run "$version" "$scripts/take.py" "$out/data/$version-default" "$count" > "$out/raw/count-$count-$trial-$version.json"
        done
    done
done
for trial in {1..5}; do
    for pages in 1 2 8 44 135; do
        space
        run final "$scripts/take.py" "$out/data/final-$pages" 128 > "$out/raw/pages-$pages-$trial.json"
    done
done
