# Wide variable-width value page splitting

This run measures full-value hashing and sampling across both the dictionary and constant-detection domains. Earlier measurements remain in the [sampling report](previous-sampling-run.md), the [proportional splitter report](previous-balanced-run.md), and the [first run report](previous-run.md).

## Builds and method

| Build | Commit |
| --- | --- |
| Baseline | `b4fb0936d12678298b36e8142f55bb0d6875a0b2` |
| Fix | `d47fe89d8e927daca956e10164edfe47bdb509ab` |

Both extensions use `release-with-debug` in separate worktrees. I reused the baseline extension and rebuilt only the fix in `/mnt/lance/target/bench-10526`. The host has 16 vCPUs. The runner verifies the existing Arrow IPC inputs against their previous SHA-256 digests. [Machine details](raw-full-value/machine.txt) · [Input verification](raw-full-value/input-check.log)

Each writer writes one batch in Lance format 2.2 with the default page limit. Table A uses one writer and 16 Lance CPU threads. The runner sums encoded buffer sizes for each page. It reads page row counts from the file metadata. It multiplies each count by 180,000 bytes for wide inputs and 8 bytes for the narrow input. The unique-wide limit check uses uncompressed value bytes and compares them with 33,734,432 bytes, the 32 MiB limit plus one 180,000-byte value.

Table B uses three trials per build and configuration, alternating baseline and fix. Each writer loads a separate copy of its IPC batch before the timer starts. The timer starts when the writer threads are released and ends when all writes complete. GNU `time -v` records peak RSS. `/proc/self/smaps_rollup` records RSS after loading the batches and before starting the writes.

Mixed-width batches can still produce oversized pages.

## Reproduce

Use a fresh raw output directory for each run. With the baseline extension already installed at the commit above, run these commands from the review worktree.

```bash
export PATH="/root/.rustup/toolchains/1.98.1-x86_64-unknown-linux-gnu/bin:$PATH"
unset CARGO_TARGET_DIR BENCH_8_WRITER_ROWS
raw="$PWD/review/issue-10526/raw-full-value"
baseline=/mnt/lance/checkouts/issue10526-base-b4fb0936d
fix=/mnt/lance/checkouts/issue10526
ipc=/mnt/lance/bench/10526/ipc
bash -n review/issue-10526/build.sh
review/issue-10526/build.sh "$baseline" "$fix" /mnt/lance/target/bench-10526 "$raw" --fix-only
review/issue-10526/measure.sh "$baseline" "$fix" "$ipc" /mnt/lance/bench/10526/output "$raw"
```

## Regression tests

At `2e3fa45`, the 20 values that shared a 64 KiB prefix stayed unsplit. They now produce ten pages. The nullable constant returned `Some([341, 342, 341])` at `2e3fa45`. It now stays unsplit and gives equal encoded byte counts at 16 MiB and `u64::MAX` in 2.1, 2.2, and 2.3.

The existing assertions passed. The encoding suite had 2,519 passing unit tests and 4 passing doc tests. The file suite had 411 passing unit tests and 6 passing doc tests. Formatting and full Clippy passed. [Test results](raw-full-value/test-results.txt)

## Results

### Wall time

| Step | Elapsed (m:ss) |
| --- | ---: |
| Fix build and install | 15:27.24 |
| IPC reuse check | 0:00.12 |
| Write matrix | 1:45.17 |
| Fix rebuild through last measurement | 18:33.65 |

### Table A. Files

| Input | Build | File B | Pages | Max encoded page B | Max uncompressed value B |
| --- | --- | ---: | ---: | ---: | ---: |
| wide-unique | baseline | 491,127,295 | 1 | 491,126,941 | 1,440,000,000 |
| wide-unique | fix | 491,134,489 | 44 | 11,175,002 | 32,760,000 |
| wide-repeated | baseline | 491,019,071 | 1 | 491,018,724 | 1,440,000,000 |
| wide-repeated | fix | 491,019,071 | 1 | 491,018,724 | 1,440,000,000 |
| narrow | baseline | 28,099,756 | 1 | 28,099,448 | 80,000,000 |
| narrow | fix | 28,099,756 | 1 | 28,099,448 | 80,000,000 |

### Table B. Median of three writes

| Writers | CPU threads | Build | Write s | Peak RSS KiB | Pre-write RSS KiB | Peak minus pre-write KiB |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 8 | baseline | 1.035 | 2,543,760 | 1,555,160 | 988,600 |
| 1 | 8 | fix | 0.787 | 2,182,416 | 1,554,832 | 627,584 |
| 1 | 16 | baseline | 0.892 | 2,549,548 | 1,554,924 | 994,548 |
| 1 | 16 | fix | 0.627 | 2,237,864 | 1,555,024 | 682,804 |
| 8 | 8 | baseline | 7.712 | 15,334,420 | 11,420,424 | 3,914,024 |
| 8 | 8 | fix | 5.474 | 15,374,816 | 11,420,560 | 3,954,276 |
| 8 | 16 | baseline | 4.614 | 18,126,624 | 11,420,412 | 6,706,108 |
| 8 | 16 | fix | 4.238 | 15,445,576 | 11,420,288 | 4,025,288 |

- 1 writer(s), 8 CPU threads, peak RSS ratio 0.8579. Pass.
- 1 writer(s), 16 CPU threads, peak RSS ratio 0.8777. Pass.
- 8 writer(s), 8 CPU threads, peak RSS ratio 1.0026. Pass.
- 8 writers, 8 CPU threads, wall-time ratio 0.7097. Pass.
- 8 writer(s), 16 CPU threads, peak RSS ratio 0.8521. Pass.

The unique-wide input produced 44 pages of 181 or 182 values each. Its largest page held 32,760,000 uncompressed value bytes and 11,175,002 encoded bytes. Its file grew by 7,194 bytes (0.00146%). The repeated-wide and narrow inputs retained their file sizes and page counts.

All 24 timing trials used 8,000 rows per writer. All file-size, page-size, peak RSS, and write-time thresholds passed. [Measured baseline extension](raw-full-value/extension-baseline.txt) · [Measured fix extension](raw-full-value/extension-fix.txt)
