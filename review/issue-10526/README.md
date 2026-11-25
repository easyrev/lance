# Issue 10526 · Linux benchmark execution record

[Verbatim handoff](handoff.md) · [PR draft](pr-draft.md)

| Role | Ref | Tested commit |
| --- | --- | --- |
| Pure | `perf/10526-wide-value-page-split` (local) | `d0020f429` |
| Review | `review/10526-wide-value-page-split` | This record |
| Upstream baseline | `upstream/main` at the pinned benchmark base | `cb8c25692` |

## Environment and commands

Debian 13.7 on AMD EPYC 9T24, 64 vCPUs with 32 exposed cores and two threads per core, and 247 GiB of OS-visible memory. Python 3.12.16, NumPy 2.5.1 and PyArrow 25.0.1. Each commit used its own virtual environment and Cargo target, with `release-with-debug`. See [machine configuration](linux-64cpu/raw/machine.txt), the [baseline](linux-64cpu/raw/extension-baseline.txt) and [final](linux-64cpu/raw/extension-fix.txt) extension hashes, and the [build](linux-64cpu/build.sh) and [measurement](linux-64cpu/measure.sh) commands.

## Results

The [summary](linux-64cpu/summary.md) places measured values alongside the original [criteria](linux-64cpu/raw/criteria.md). The [method and reproduction commands](linux-64cpu/README.md) describe the inputs and timing intervals. The [raw records](linux-64cpu/raw/) include 18 file writes, 18 exact round trips, 54 scans, 54 random takes and 44 matrix writes including eight warmup writes. The [manifest](linux-64cpu/SHA256SUMS) covers the archived raw files.

## Execution changes and retries

- GNU time was missing. The first build launch exited 127 before compiling. The retry used Bash time for the build and Python process metrics for the benchmark.
- A separate baseline narrow-input smoke run checked metadata and reading while final was compiling. The nine formal IPC inputs were generated during that compilation. Formal write and read timings began after both builds completed.
- Each file pair was removed after its own correctness and read runs. File and read work for that pair finished before the next dataset pair started.
- The first commit attempt stopped while installing a hook from the host's Python package mirror. The retry used the public PyPI index. The pre-commit checks completed.
