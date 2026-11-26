#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
raw=$task/raw
cd /root/lance/repo
git diff --stat cb8c25692 d0020f429 > "$raw/stage0-final-diff-stat.txt"
git diff --name-only cb8c25692 d0020f429 > "$raw/stage0-final-files.txt"
git diff --name-only 154270cf1 1d24f80fd > "$raw/stage0-b-files.txt"
comm -12 <(sort "$raw/stage0-final-files.txt") <(sort "$raw/stage0-b-files.txt") > "$raw/stage0-file-intersection.txt"
git rev-parse perf/10526-wide-value-page-split > "$raw/stage0-10526-head.txt"
{
    lscpu
    free -h
    uname -a
    rustc --version
    uv --version
    df -h / /dev/shm
} > "$raw/machine.txt"
