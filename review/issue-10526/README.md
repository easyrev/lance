# Wide variable-width value page splitting

This run tests proportional page boundaries with a greedy fallback. The earlier run measured the original splitter and is archived with its raw results. [Earlier report](previous-run.md)

| Build | Commit |
| --- | --- |
| Baseline | `651858fb229a8e9e3ecca6790aea5e1875e3efae` |
| Fix | `343e36aecc953cb8278707b751e5129813a1094f` |

Both Python extensions used the repository's `release-with-debug` profile and separate worktrees. The baseline extension was reused and its digest matched the earlier run. Only the fix extension was rebuilt, using the same shared Cargo target at `/mnt/lance/target/bench-10526`. The host had 16 vCPUs on an AMD EPYC 9T25 and 66,196,975,616 bytes of visible RAM. [Machine details](raw-balanced/machine.txt)

## Reproduce

Run these commands from the review worktree with the baseline extension installed at the commit above. Use a fresh raw output directory for a new run.

```bash
export PATH="/root/.rustup/toolchains/1.98.1-x86_64-unknown-linux-gnu/bin:$PATH"
unset CARGO_TARGET_DIR BENCH_8_WRITER_ROWS
raw="$PWD/review/issue-10526/raw-balanced"
bash -n review/issue-10526/build.sh
review/issue-10526/build.sh \
    /mnt/lance/checkouts/issue10526-base /mnt/lance/checkouts/issue10526 \
    /mnt/lance/target/bench-10526 "$raw" --fix-only
review/issue-10526/measure.sh \
    /mnt/lance/checkouts/issue10526-base /mnt/lance/checkouts/issue10526 \
    /mnt/lance/bench/10526/ipc /mnt/lance/bench/10526/output "$raw"
```

The committed `build.sh` passed `bash -n` and matched the executed script byte for byte. The run checked the existing Arrow IPC files against the earlier run's hashes before reusing them. [Build script verification](raw-balanced/build-script.txt) · [Input verification](raw-balanced/input-check.log)

The first fix-only attempt used `maturin develop` and selected a different ABI setup. I canceled it before measurement and rebuilt by reinstalling only `pylance` with the same editable PEP 517 build path as the baseline. [Interrupted build log](raw-balanced-attempt/build-fix.log)

The unique input contains 8,000 strings of exactly 180,000 bytes. Each string starts with an eight-digit row number followed by draws from a fixed-seed vocabulary of 4,096 synthetic words. The repeated input takes the first 100 strings and repeats each one 80 times. The narrow input has 10,000,000 consecutive `int64` values.

Each writer loads its own copy of the IPC batch before the timer starts and writes a separate Lance dataset in format 2.2 with the default page limit. The limit compares uncompressed value bytes. Table A reports the sum of the encoded buffers for the largest page, using one writer and 16 Lance CPU threads. Table B alternates baseline and fix for each trial and measures elapsed time from the release of the writer threads through completion of all writes. GNU `time -v` records peak RSS. `/proc/self/smaps_rollup` records pre-write RSS after the batches are loaded.

## Code and tests

The first pass greedily packs values up to the page limit. The second pass uses proportional boundaries based on each value's byte midpoint and retains the same cap. The planner uses proportional boundaries only when the page count matches the greedy pass. Both passes use `u128` for byte arithmetic.

The seven specified examples pass. The random invariant test checks that the result uses the same number of pages as greedy packing. The 8,000-value benchmark shape produces 44 pages of 181 or 182 values. The encoder and file expectations passed as written, including the encoded-buffer size limit, round trips, and the zero-limit regression. Formatting and full Clippy passed. The encoding suite had 2,503 passing unit tests and 4 passing doc tests. The file suite had 411 passing unit tests and 6 passing doc tests. [Original implementation and size comparison](previous-run.md#code-and-tests)

## Results

### Wall time

| Step | Elapsed (m:ss) |
| --- | ---: |
| Fix build and install | 17:51.23 |
| IPC reuse check | 0:00.12 |
| Write matrix | 1:42.68 |
| Successful rebuild through last measurement | 21:19.84 |

### Table A. Files

| Input | Baseline file B | Pages | Max page B | Fix file B | Pages | Max page B |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| wide-unique | 491,127,295 | 1 | 491,126,941 | 491,134,489 | 44 | 11,175,002 |
| wide-repeated | 491,019,071 | 1 | 491,018,724 | 491,019,071 | 1 | 491,018,724 |
| narrow | 28,099,756 | 1 | 28,099,448 | 28,099,756 | 1 | 28,099,448 |

### Table B. Median of three writes

| Writers | CPU threads | Build | Write s | Peak RSS KiB | Pre-write RSS KiB | Peak minus pre-write KiB |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 8 | baseline | 1.028 | 2,543,052 | 1,555,244 | 987,828 |
| 1 | 8 | fix | 0.755 | 2,179,172 | 1,554,912 | 624,460 |
| 1 | 16 | baseline | 0.890 | 2,548,912 | 1,555,048 | 993,876 |
| 1 | 16 | fix | 0.594 | 2,237,360 | 1,555,060 | 682,300 |
| 8 | 8 | baseline | 7.624 | 15,225,372 | 11,420,432 | 3,804,768 |
| 8 | 8 | fix | 5.282 | 15,355,608 | 11,420,468 | 3,935,440 |
| 8 | 16 | baseline | 4.433 | 17,727,232 | 11,420,452 | 6,306,452 |
| 8 | 16 | fix | 4.143 | 15,440,248 | 11,420,576 | 4,019,672 |

- 1 writer(s), 8 CPU threads, peak RSS ratio 0.8569. Pass.
- 1 writer(s), 16 CPU threads, peak RSS ratio 0.8778. Pass.
- 8 writer(s), 8 CPU threads, peak RSS ratio 1.0086. Pass.
- 8 writers, 8 CPU threads, wall-time ratio 0.6927. Pass.
- 8 writer(s), 16 CPU threads, peak RSS ratio 0.8710. Pass.

The largest unique-wide page was 11,175,002 compressed bytes. The page-size check compares the largest encoded page against 33,734,432 bytes, which is the **32 MiB limit plus one 180,000-byte value**. The unique-wide file grew by 7,194 bytes (0.00146%). Repeated-wide and narrow inputs produced identical page counts and file sizes. All file checks passed. Each of the 24 timing runs used 8,000 rows per writer.

Cargo reported 17m 48s for compilation. Wall time from the first rebuild attempt through the last measurement was 23m 17.29s. The timing table measures the successful rebuild and rerun separately. [Fix build log](raw-balanced/build-fix.log) · [File checks](raw-balanced/file-checks.jsonl)
