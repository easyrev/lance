# Issue 10526 decode follow-up execution record

[Verbatim handoff](handoff.md) · [Existing PR draft](pr-draft.md)

## Branches and tested commits

| Role | Ref | Commit |
| --- | --- | --- |
| Upstream baseline | Pinned upstream tree | `cb8c25692e0d35d682be5459644a698f8d49655a` |
| Page splitting | `perf/10526-wide-value-page-split` | `d0020f4291a0cb18790ac731df7c24890a169ca1` |
| Experiment A | Parent of experiment B | `154270cf1fe06ff34524ca1fdcadbc8743302557` |
| Experiment B | `exp/10526-decode-page-bridging` | `1d24f80fd2cae75eb81b2836be59256b3a2df4f4` |
| Review | `review/10526-wide-value-page-split` | This record |
| Upstream PR | None opened in this round | |

## Environment and commands

The four builds used the same 64-vCPU Linux host and the `release-with-debug` profile.
The baseline and final used their existing targets and editable extensions. The
experiment worktree used its own target and virtual environment, first for A and then
for B. Measurements used 64 Lance CPU threads and tmpfs dataset files. The report
links to the machine, extension, dataset, and trial records. [Four-build report](linux-64cpu/decode-followup.md)

Run the scripts with the `/root/lance` worktree layout and the original inputs in
`/dev/shm/lance-10526/ipc`. The common script records both disk-space checks and
checks the 10 GiB floor. [Original input generator](linux-64cpu/bench.py) · [Commands and raw data](linux-64cpu/decode-followup/)

| Step | Command or script |
| --- | --- |
| Twelve alternating base/final repeated-take processes | [phase1.sh](linux-64cpu/decode-followup/phase1.sh) |
| Build and check experiment A at its commit | [build-experiment.sh exp-A](linux-64cpu/decode-followup/build-experiment.sh) |
| Rebuild additional 8k and mixed fixtures | [prepare-phase2.sh](linux-64cpu/decode-followup/prepare-phase2.sh) |
| Rerun A Rust tests after correcting the test call | [retest-A.sh](linux-64cpu/decode-followup/retest-A.sh) |
| Read trials for baseline, final and A | [run-measure-A.sh](linux-64cpu/decode-followup/run-measure-A.sh) |
| Build, check and measure the B commit | [run-B.sh](linux-64cpu/decode-followup/run-B.sh) |
| Generate comparison and manifest | [archive.sh](linux-64cpu/decode-followup/archive.sh) |

## Results

The table reports three fresh processes per build and measurement, with all 20 calls
for each repeated take. It includes four-build medians and ranges, exact full scan and
nonsequential take checks, and comparison to the original 8k scan RSS criterion.
[Measurement tables](linux-64cpu/decode-followup.md) · [Raw files](linux-64cpu/decode-followup/raw/) · [SHA256SUMS](linux-64cpu/decode-followup/SHA256SUMS)

## Execution changes and retries

- The original Arrow IPC inputs were present and their hashes matched the earlier run.
  The original Lance outputs had been removed, so the writer recreated them under the
  follow-up scratch directory. Both experiments recorded the same final file hashes
  and page counts as the current final baseline.
- The take harness added a process high-water RSS counter after each timed call. It
  retained the same row selection, handle lifetime, and timing boundaries.
- The first A test compile exited 101 because the test used an ambiguous trait method.
  Qualifying the method resolved the ambiguity. The build and measurement used the
  amended A commit. [Initial compiler output](linux-64cpu/decode-followup/raw/test-exp-A-initial.log)
- B was drafted and prechecked in a detached worktree while A compiled. The shared-buffer
  API is declared in `compression.rs`, which owns the decompressor trait. The formal B
  checks and measurements ran in the experiment worktree. The B diff spans five files
  with 364 additions and 18 deletions including tests.
- The 1,024 rows contain 184.32 MB of values, equivalent to 175.78 MiB.
