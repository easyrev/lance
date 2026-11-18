# Wide variable-width value page splitting

The fix branch contains the encoder change, tests, and documentation. This branch adds the measurement scripts and raw results.

| Build | Commit |
| --- | --- |
| Baseline | `651858fb229a8e9e3ecca6790aea5e1875e3efae` |
| Fix | `93acbc4d37c3d6ba4cc41bde4c3c760a4d5c344d` |

Both Python extensions used the repository's `release-with-debug` profile, Python 3.12, and Rust 1.98.1. The builds ran sequentially in separate worktrees with a shared Cargo target for measurement builds. The host had 16 vCPUs on an AMD EPYC 9T25, 66,196,975,616 bytes of visible RAM, and NVMe storage for the builds, IPC inputs, and output files. [Machine details](raw/machine.txt)

## Reproduce

Run these commands from the review worktree with the baseline and fix worktrees at the commits above.

```bash
export PATH="/root/.rustup/toolchains/1.98.1-x86_64-unknown-linux-gnu/bin:$PATH"
unset CARGO_TARGET_DIR
review/issue-10526/build.sh \
    /mnt/lance/checkouts/issue10526-base /mnt/lance/checkouts/issue10526 \
    /mnt/lance/target/bench-10526 "$PWD/review/issue-10526/raw"
review/issue-10526/measure.sh \
    /mnt/lance/checkouts/issue10526-base /mnt/lance/checkouts/issue10526 \
    /mnt/lance/bench/10526/ipc /mnt/lance/bench/10526/output \
    "$PWD/review/issue-10526/raw"
```

The generator saves one uncompressed Arrow IPC batch per input. The unique input has 8,000 strings of exactly 180,000 bytes. Each string starts with an eight-digit row number, followed by draws from a fixed-seed vocabulary of 4,096 distinct synthetic seven-letter words separated by spaces. The repeated input takes the first 100 strings and repeats each one 80 times. The narrow input has 10,000,000 consecutive `int64` values.

Each writer loads its own copy of the IPC batch before the timer starts and writes a separate Lance dataset in format 2.2 with the default page limit. File measurements use one writer and 16 Lance CPU threads. The maximum page size sums the buffer sizes of each page in the single data column. The write matrix alternates baseline and fix for each trial and measures elapsed time from the release of the writer threads through completion of all writes. Peak RSS comes from GNU `time -v`. Pre-write RSS comes from `/proc/self/smaps_rollup` after loading the batches.

Use a fresh raw output directory to record a new run. The recorded IPC generation and baseline file checks ran while the fix was building. The timing matrix ran after both builds completed.

## Code and tests

The fix adds the shared compression threshold in `compression.rs`, the page-count logic in `wide_value_split.rs`, and the dense page planning calls in `structural_encoder.rs` and `planar.rs`. It adds tests in the splitter module, `structural_encoder/tests.rs`, and `writer_tests.rs`. It also corrects the comments in the 2.0 writer, Rust writer tests, and Python file tests, and updates the `LanceFileWriter` docstring.

The array-slicing call uses the existing `u64` arguments and propagates `Result`. The rep/def fallback is private because it has one caller. The new test helper also serves the existing first-page tests, and the round-trip tests assert that the input spans multiple pages. The review amendment preserves one page when a caller constructs `EncodingOptions` with a zero limit. The file-writer validation of zero still applies at its existing entry points.

The encoded-buffer size test gave 813 bytes split and 831 bytes unsplit in 2.1, 2.2, and 2.3. The zero-limit case reproduced the divide-by-zero panic in all three versions before the review amendment. After the amendment, formatting, both crate test suites, and full Clippy passed. The encoding suite had 2,502 passing unit tests and 4 passing doc tests. The file suite had 411 passing unit tests and 6 passing doc tests.

## Results

### Wall time

| Step | Elapsed (m:ss) |
| --- | ---: |
| Baseline build and install | 19:43.37 |
| Fix build and install | 15:17.77 |
| Arrow IPC generation | 0:03.78 |
| Write matrix | 1:46.23 |
| End to end | 37:59.46 |

### Table A. Files

| Input | Baseline file B | Pages | Max page B | Fix file B | Pages | Max page B |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| wide-unique | 491,127,295 | 1 | 491,126,941 | 491,133,910 | 44 | 11,420,339 |
| wide-repeated | 491,019,071 | 1 | 491,018,724 | 491,019,071 | 1 | 491,018,724 |
| narrow | 28,099,756 | 1 | 28,099,448 | 28,099,756 | 1 | 28,099,448 |

### Table B. Median of three writes

| Writers | CPU threads | Build | Write s | Peak RSS KiB | Pre-write RSS KiB | Peak minus pre-write KiB |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 8 | baseline | 1.039 | 2,542,868 | 1,555,032 | 987,884 |
| 1 | 8 | fix | 0.750 | 2,179,668 | 1,555,188 | 624,480 |
| 1 | 16 | baseline | 0.877 | 2,548,720 | 1,555,084 | 993,636 |
| 1 | 16 | fix | 0.627 | 2,248,620 | 1,555,124 | 693,436 |
| 8 | 8 | baseline | 7.628 | 15,171,140 | 11,420,404 | 3,750,772 |
| 8 | 8 | fix | 5.271 | 15,378,688 | 11,420,416 | 3,958,176 |
| 8 | 16 | baseline | 4.490 | 17,928,908 | 11,420,628 | 6,508,280 |
| 8 | 16 | fix | 4.174 | 15,449,288 | 11,420,516 | 4,028,540 |

- 1 writer(s), 8 CPU threads, peak RSS ratio 0.8572. Pass.
- 1 writer(s), 16 CPU threads, peak RSS ratio 0.8823. Pass.
- 8 writer(s), 8 CPU threads, peak RSS ratio 1.0137. Pass.
- 8 writers, 8 CPU threads, wall-time ratio 0.6910. Pass.
- 8 writer(s), 16 CPU threads, peak RSS ratio 0.8617. Pass.

The unique-wide maximum page was 11,420,339 bytes against a limit of 33,734,432 bytes. Its file grew by 6,615 bytes (0.00135%). The repeated and narrow inputs produced identical page counts and file sizes. All stop conditions were clear. All timing trials used 8,000 rows per writer.

The end-to-end wall time covers the start of the baseline build through the last measurement. Cargo reported 19m 03s for the baseline compile and 14m 43s for the fix compile. Build-and-install times include Python environment setup. Cargo compiled 710 packages for the baseline and 24 for the fix. [Baseline build log](raw/build-baseline.log) · [Fix build log](raw/build-fix.log)

I added the reproducibility timestamp to the build wrapper while Bash was still reading it. The wrapper reported a syntax error after both build-and-install commands exited successfully. The measured extensions were installed in separate worktrees, and the runner verified their separate paths and distinct hashes before measuring. [Wrapper diagnostic](raw/build-wrapper.log) · [Baseline extension](raw/extension-baseline.txt) · [Fix extension](raw/extension-fix.txt)
