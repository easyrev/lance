# Wide variable-width value page splitting

This run tests dictionary-aware sampling on the rebased fix. Earlier runs and their evidence are preserved in the [proportional splitter report](previous-balanced-run.md) and the [first run report](previous-run.md).

## Builds and method

The baseline is upstream `b4fb0936d12678298b36e8142f55bb0d6875a0b2`. The measured fix is `8d39b384c1b609adbfc7553986ce40cf3ed0a1e6`, based on the same commit. The 15 commits added upstream since `651858fb2` changed neither `rust/lance-encoding` nor `rust/lance-file`.

The follow-up only changes split eligibility when null slots carry payloads. The benchmark inputs have no nulls, so the tables retain the measurements from `8d39b38`.

Both extensions use `release-with-debug` in separate worktrees. The builds share `/mnt/lance/target/bench-10526`. The host has 16 vCPUs. The measurement reuses the Arrow IPC inputs from the earlier runs and verifies their SHA-256 digests. [Machine details](raw-sampling/machine.txt) · [Input verification](raw-sampling/input-check.log)

The first fix build command reused the previously installed extension. I discarded that run after comparing the binary hash with the previous run. The committed build script forces a fresh `pylance` build for the fix. It passed `bash -n` and matched the script used for the successful rebuild. [Script hashes](raw-sampling/scripts.txt) · [Skipped build log](raw-sampling/skipped-fix-build.log)

Each writer writes one batch per dataset in Lance format 2.2 with the default page limit. Table A uses one writer and 16 Lance CPU threads. For each page, the script sums the sizes of the encoded buffers. It reads each page's row count from the file's column metadata with `protoc`. It multiplies the count by 180,000 bytes for either wide input and by 8 bytes for the narrow input. For the unique-wide input, the limit check compares uncompressed value bytes with 33,734,432 bytes, the **32 MiB limit plus one 180,000-byte value**. The earlier runs compared encoded bytes for this check. The file-size and unchanged-output checks use the actual files.

Table B uses three trials per build and configuration, alternating baseline and fix. Each writer loads a separate copy of the IPC batch before the timer starts. The timer measures the interval from releasing the writer threads to completion of all writes. GNU `time -v` records process peak RSS. `/proc/self/smaps_rollup` records pre-write RSS after the batches are loaded.

## Reproduce

Run these commands from the review worktree. Use a fresh raw output directory for each new run. The IPC directory must contain the inputs from the first run to reproduce the same comparison.

```bash
export PATH="/root/.rustup/toolchains/1.98.1-x86_64-unknown-linux-gnu/bin:$PATH"
unset CARGO_TARGET_DIR BENCH_8_WRITER_ROWS
raw="$PWD/review/issue-10526/raw-sampling"
baseline=/mnt/lance/checkouts/issue10526-base-b4fb0936d
fix=/mnt/lance/checkouts/issue10526
ipc=/mnt/lance/bench/10526/ipc
bash -n review/issue-10526/build.sh
review/issue-10526/build.sh "$baseline" "$fix" /mnt/lance/target/bench-10526 "$raw"
review/issue-10526/measure.sh "$baseline" "$fix" "$ipc" /mnt/lance/bench/10526/output "$raw"
```

## Regression tests

The old planner returned `Some([341, 341, 342])` for the default dictionary-limit fixture. It also produced different encoded sizes at 16 MiB and at `u64::MAX` in all three structural versions. Sampling by non-null rank keeps the fixture unsplit. The encoded sizes now match in 2.1, 2.2, and 2.3. The custom dictionary-limit case and the 70,000-row pure-validity guard pass.

At `8d39b38`, the encoding suite had 2,509 passing unit tests and 4 passing doc tests. The file suite had 411 passing unit tests and 6 passing doc tests. Formatting and full Clippy passed.

The follow-up samples non-empty physical slots, including payloads under nulls, because the dictionary encoder interns them. A null slot can be empty or contain more than 32 KiB. Every valid slot must contain more than 32 KiB.

At `8d39b38`, the planner returned `Some([341, 342, 341])` for the fixture with 255 valid rows and 769 nulls carrying payloads. The follow-up keeps this fixture on one page at both limits in 2.1, 2.2, and 2.3. The encoded data byte counts match. A separate regression checks that a 10-byte null payload prevents splitting.

The follow-up encoding suite had 2,514 passing unit tests and 4 passing doc tests. The file suite had 411 passing unit tests and 6 passing doc tests. Existing assertions passed, including the tests for splitting pages with empty null slots.

I also ran a temporary probe at `8d39b38` using fixed-seed random payloads (`SmallRng`, seed 10526). Encoded bytes are the sum of the page buffer sizes.

| Version | 16 MiB pages | 16 MiB encoded bytes | Unlimited pages | Unlimited encoded bytes |
| --- | ---: | ---: | ---: | ---: |
| 2.1 | 3 | 8,364,434 | 1 | 8,359,337 |
| 2.2 | 3 | 8,364,434 | 1 | 8,391,350 |

Splitting added 5,097 encoded bytes in 2.1 and saved 26,916 encoded bytes in 2.2. The respective on-disk file sizes were 8,364,835 and 8,359,739 bytes in 2.1, and 8,364,835 and 8,391,759 bytes in 2.2.

## Results

### Wall time

| Step | Elapsed (m:ss) |
| --- | ---: |
| Baseline build and install | 15:55.70 |
| Fix build and install | 14:51.04 |
| IPC reuse check | 0:00.12 |
| Write matrix | 1:43.58 |
| Fix rebuild through last measurement | 17:47.55 |

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
| 1 | 8 | baseline | 1.066 | 2,543,916 | 1,555,236 | 988,680 |
| 1 | 8 | fix | 0.771 | 2,166,412 | 1,554,892 | 611,520 |
| 1 | 16 | baseline | 0.909 | 2,549,660 | 1,555,004 | 994,656 |
| 1 | 16 | fix | 0.616 | 2,230,132 | 1,555,020 | 675,184 |
| 8 | 8 | baseline | 7.632 | 15,160,568 | 11,420,540 | 3,739,816 |
| 8 | 8 | fix | 5.280 | 15,373,640 | 11,420,512 | 3,953,004 |
| 8 | 16 | baseline | 4.457 | 17,646,804 | 11,420,408 | 6,226,520 |
| 8 | 16 | fix | 4.153 | 15,451,316 | 11,420,436 | 4,030,860 |

- 1 writer(s), 8 CPU threads, peak RSS ratio 0.8516. Pass.
- 1 writer(s), 16 CPU threads, peak RSS ratio 0.8747. Pass.
- 8 writer(s), 8 CPU threads, peak RSS ratio 1.0141. Pass.
- 8 writers, 8 CPU threads, wall-time ratio 0.6919. Pass.
- 8 writer(s), 16 CPU threads, peak RSS ratio 0.8756. Pass.

All file checks passed. The unique-wide write produced 44 pages of 181 or 182 values each. The largest page held 32,760,000 uncompressed value bytes and 11,175,002 encoded bytes. The unique-wide file grew by 7,194 bytes (0.00146%). The repeated-wide and narrow inputs kept their file sizes and page counts.

The full elapsed time was 36m 42.77s from the rebased baseline build through the last measurement. This includes the discarded run. The timing matrix contains 24 valid runs with 8,000 rows per writer. [Measured baseline extension](raw-sampling/extension-baseline.txt) · [Measured fix extension](raw-sampling/extension-fix.txt)
