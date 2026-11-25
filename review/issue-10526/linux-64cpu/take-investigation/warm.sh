#!/bin/bash
set -euo pipefail
work=/dev/shm/lance-10526/take-investigation
cd /root/lance/final/python
export LANCE_CPU_THREADS=64
for trial in {1..5}; do
    for pages in 1 135; do
        .venv/bin/python /root/lance/tmp/take10526/take.py "$work/data/final-$pages" 128             --take-only --repeat 2 > "$work/raw/reuse-$pages-$trial.jsonl"
    done
done
for pages in 1 135; do
    strace -f -qq -yy -ttt -T -s 0 -e trace=pread64,write         -o "$work/raw/reuse-pread-$pages.log"         .venv/bin/python /root/lance/tmp/take10526/take.py "$work/data/final-$pages" 128         --take-only --repeat 2 > "$work/raw/reuse-pread-$pages.jsonl"
done
