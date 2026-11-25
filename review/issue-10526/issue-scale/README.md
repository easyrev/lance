# Lance #10526 local follow-up

Question: Validate the wide-value split gate after review and measure one 4.5 GB record batch against its exact upstream base.

Done when: The local commit, complete suite and lint outcomes, benchmark readback, and review draft are available for the publishing thread.

## Source and reproduction

- Upstream baseline: `cb8c25692`.
- Starting fix: `fde471a51`.
- Review follow-up: `d0020f4291a0cb18790ac731df7c24890a169ca1`.
- Run `bash /path/to/evidence/verify.sh` from that final checkout. Optionally set `CARGO_TARGET_DIR` for verification and `BENCH_TARGET_ROOT` for an absolute parent of two independent benchmark target directories. This runs sequentially and writes a log and exit file per step. `bash /path/to/evidence/benchmark.sh` repeats just the A/B. Both builds use the same repository profile, source harness, worker settings, and writer defaults.
- The benchmark script creates a detached temporary upstream worktree and temporarily installs the same example source on both revisions. The temporary worktree, harness copies, and copied binaries are cleaned up by the script. Cargo retains its build cache outside this evidence folder. The file fixture uses a local temporary file.
- The first A/B used a shared Cargo output directory. The final build only rebuilt the example and reproduced baseline's exact file. Those unfit measurements are preserved in `shared-target-attempt/`. The rerun isolates artifact directories per revision and checks expected page counts before admitting a trial.
- The local run uses the existing MBX target cache at `~/Library/Caches/mbx/targets/v1/4659730bb613cd3ecf7727b724ac8e23c9997940b29ff154af0b3f3df2370eae`. See `machine.txt` for the toolchain and host.

## What is measured

Format 2.2, one call to `write_batch` with 25,000 LargeBinary values of 180,000 bytes each. A fixed-seed 4 KiB byte pattern repeats within each value and the first eight bytes encode the row id. The full input fingerprint is recorded before timing and matched across builds. Generation and fingerprinting are outside the write interval. The write interval includes creation, the one batch call, and finish. Process CPU includes user and system time across all writer threads. Average cores divides that CPU delta by wall elapsed seconds.

The streaming full scan checks every row against the input. Sorted random take uses 128 distinct row ids from the fixed-seed RNG after pattern generation and verifies their exact bytes. Scan and take timings include readback checks, with verification time also recorded separately. The reader reuses the file after the write, and take follows the scan, so these are warm local reads. The build uses eight Tokio workers and sets `LANCE_CPU_THREADS=8` and `RAYON_NUM_THREADS=8`. A warmup precedes three paired measurements. Sampling once per second captures kernel memory pressure, swap usage, and process RSS. A pressure warning or 512 MiB cumulative swap growth stops the run.

## Scope

The default byte proof uses at most 256 non-empty physical probes plus up to 256 valid probes, deduplicated by row. A probe can hash a full wide value. A miss can leave an oversized page, including 31,000-byte mostly-short distributions. A logical constant can still incur sampling and comparison cost before its normal layout is selected. Prior timing comparisons had roughly 10% variation. This workload measures a single highly compressible distribution and warm local reads.

## Fixture accounting

The default dictionary budget is 8,388,608 bytes. For 32,769-byte values the physical probe selects 256 ranks. Unique 257- and 340-row inputs each expose 8,388,864 bytes. The fixture with 255 distinct values in 341 rows exposes 213 distinct values to the probe, or 6,979,797 bytes. The positions and values follow `floor(probe * rows / 256) % fixture_distinct`. [Accounting table](sample-fixtures.tsv)

The entry-limit regression sets the field divisor explicitly. With 21 distinct wide values in 21 physical rows, divisor 2 allows the split and divisor 1 does not. Adding empty null slots makes the physical denominator 43 despite only 21 valid values. The lower bound of 21 non-empty dictionary entries meets that limit and the planner leaves the batch unsplit.

## Results

[Benchmark results](benchmark-results.md) · [Verification results](verification-results.md) · [Process and status log map](jobs.md) · [PR draft](pr-draft.md)
