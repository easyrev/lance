# Linux benchmarks for #10526
[Random take investigation](take-investigation.md) compares open and take latency, page counts, and CPU samples.

See [summary.md](summary.md) for results and [raw/](raw/) for individual observations, page encodings, correctness checks, build and run logs, host configuration, and hashes. The two measured commits were upstream `cb8c25692` and final `d0020f429`. Both used format 2.2, Python 3.12, the `release-with-debug` profile, independent environments and target directories, and default Linux scheduling. See [machine.txt](raw/machine.txt) for the complete host record.

## Inputs

The November 18 generator uses NumPy's RNG seeded with 10526. Each distinct 180,000-byte LargeUtf8 value begins with an eight-digit row identifier followed by random draws from 4,096 seven-letter words with space separators. The IPC inputs are shared by the builds and their hashes are recorded. Each write process loads an independent copy per writer into memory before timing.

| Dataset | Input |
| --- | --- |
| wide-unique | 25,000 distinct wide values |
| wide-unique-8k | 8,000 distinct wide values |
| wide-low-card | 25,000 rows with 10 distinct wide values, shuffled |
| wide-repeated | 100 distinct wide values, each repeated 80 times |
| wide-template | 25,000 wide values, with 5% of rows sharing one value and the rest distinct |
| wide-clustered | 50 distinct wide values, each repeated in a contiguous run of 500 rows |
| wide-mixed | 25,000 shuffled rows with 95% distinct wide values, 4% 104-byte strings, 0.5% empty strings and 0.5% nulls |
| wide-constant | 25,000 copies of one wide value |
| narrow | 10 million successive int64 values, as in the November 18 benchmark |

## Execution

The file stage uses one writer and 64 Lance CPU threads. Page raw size sums the logical value payload in its rows. Encoded page size sums its on-disk buffers. Each output is read in a dedicated process and checked against the input, batch by batch. The same output then serves three separately launched scan and take processes per mode. Timed reads include dataset open. The scan consumes 1,024-row batches, and the take uses 128 sorted unique row numbers from seed 10526. The timed reader validates the row count. The verification process performs the value comparison.

The write matrix uses a Python thread pool and a barrier, with a fresh process for each variant and trial. There is one warmup and three measured runs for each 1/8 writer × 8/64 thread combination. The 8-writer input is the same 8,000 rows per writer. The clustered and mixed cases add three measured runs each at 1 writer and 64 CPU threads. Process CPU time measures user and system time inside the same interval as write wall time. RSS is the process high-water mark, including input copies for writers. The pre-write RSS is recorded separately. Each pair runs upstream then final. All IPC data and measurement outputs use tmpfs. File-stage datasets are removed after their verification and reads. Write-matrix datasets are removed after each process finishes.

The scripts here extend the November 18 harness. On the same host layout, run `bash build.sh` and then `bash run-measure.sh`, with this directory as the source of the scripts.
