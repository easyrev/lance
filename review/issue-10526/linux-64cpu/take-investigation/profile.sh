#!/bin/bash
set -euo pipefail
work=/dev/shm/lance-10526/take-investigation
cd /root/lance/final/python
export LANCE_CPU_THREADS=64
export PERF_BUILDID_DIR="$work/perf-buildid"
for pages in 1 135; do
    df -h / /dev/shm >> "$work/raw/space.log"
    for mount in / /dev/shm; do
        (( $(df -B1 --output=avail "$mount" | tail -1) >= 10737418240 ))
    done
    ctrl="$work/control-$pages"
    ack="$work/ack-$pages"
    rm -f -- "$ctrl" "$ack"
    mkfifo "$ctrl" "$ack"
    timeout 45 perf record --no-buildid-cache --delay=-1 --control="fifo:$ctrl,$ack"         -e cpu-clock -F 499 --call-graph dwarf,8192 -o "$work/perf-$pages.data" --         .venv/bin/python /root/lance/tmp/take10526/take.py "$work/data/final-$pages" 128         --take-only --repeat 35 --perf-control "$ctrl" "$ack" > "$work/raw/perf-$pages-timings.jsonl"         2> "$work/raw/perf-$pages-record.log"
    perf report --no-inline --stdio --percent-limit 0.8 -i "$work/perf-$pages.data"         > "$work/raw/perf-$pages-report.txt"
    perf report --no-inline --stdio --no-children --percent-limit 0.5 -i "$work/perf-$pages.data"         > "$work/raw/perf-$pages-self.txt"
done
