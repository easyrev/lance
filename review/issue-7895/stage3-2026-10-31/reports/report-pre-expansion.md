# #9617 Stage 3 preflight report

## Decision

I did not start Experiment 1.

The initial data-disk free space was 81,846,726,656 bytes, or 76.23 GiB.
The 20% reserve is 15.23 GiB.
The usable budget was 60.98 GiB.

The Experiment 1 peak estimate is 88 GiB.
It includes 43 GiB of retained source files and the original 12 GiB target.
It also includes about 16 GiB of new target data and about 16 GiB of U replay spill.
The estimate exceeds the usable budget by 27.02 GiB.

The same peak requires 110 GiB of total free space after the 20% reserve.
The shortfall against the initial 76.23 GiB is 33.77 GiB.
Add at least 40 GiB to the data disk and rerun the 12-hour gate.

I deleted the unused 54 GiB Experiment 1 fixture after the stop decision.
The generation script can recreate it.
The current free space is 81,845,710,848 bytes, or 76.22 GiB.

## Stage 2b gate

The gate passed.
Stage 2b ended with rule (a).
The Blob V2 additions did not work on `f9a5c662d` or `15a523ffc`.
The work deleted those additions from commit 2.
The final commit is `9767241c21d4124dc2f8d24d642abe93c8ca859c`.

The saved Stage 2b record reports these checks as passed:

| Check | Result |
|---|---|
| Full Python dataset suite | 424 passed, 5 skipped |
| Native source and fallback subset | 21 passed |
| Native Rust FirstSeen test | Passed |
| Replayable tests | 4 passed |
| Python lint | Passed |
| Workspace clippy | Passed |
| Formatting and diff check | Passed |

The repository is clean on `feat/7895-rescannable-sources` at
`9767241c21d4124dc2f8d24d642abe93c8ca859c`.
`issue-drafts/` is outside the repository at `/mnt/lance/9617-notes/issue-drafts/`.

## Builds

The report uses the three existing preflight wheels.
The Cargo build profile was `release`.
The build command was `maturin build --release`.
No wheel was rebuilt.

| Build | Commit | Wheel SHA256 |
|---|---|---|
| U | `f9a5c662d79ac312d16d8f636cb1feba4e84aee8` | `e6b3c0b15f816027d757430cca09b7b08b92ebc0e67d905b30cd5e65ea33d6fc` |
| P1 | `15a523ffcc93e6d2c73ad2af69a1e6420efcdc22` | `28e861a077701abbbf97a924525bf6ab1d70c06674bc1bfe4874e0917294d73a` |
| P2 | `9767241c21d4124dc2f8d24d642abe93c8ca859c` | `5b9945c84d399258ebe04d7a5cad604f03d846666d76559458e0e3aa8e478e05` |

## Host

| Item | Value |
|---|---|
| CPU | AMD EPYC 9T25, 16 vCPUs |
| Memory | 61 GiB, no swap |
| OS | Ubuntu 24.04.5 LTS |
| Kernel | Linux 6.8.0-139-generic |
| Device `nvme0n1` | Alibaba Cloud Elastic Block Storage, 300 GB |
| Device `nvme1n1` | Alibaba Cloud Elastic Block Storage, 50 GB |

The devices use the NVMe transport.
The `lsblk` model identifies both devices as Alibaba Cloud Elastic Block Storage.
The device name alone does not prove a locally attached NVMe disk.

All three virtual environments had Python 3.12.3, Lance 15.0.0b7, PyArrow 25.0.1, and NumPy 2.5.4.

## Harness

I found no earlier #9617 benchmark harness on this host.
The new harness is under `/mnt/lance/9617-bench`.

The harness has these controls:

- It starts one isolated child process per run.
- It uses `wait4` for CPU time and peak RSS.
- It measures wall time around `execute()` only.
- It samples the peak size of a run-specific `TMPDIR`.
- It verifies row count, version count, and sampled values across every column.
- It resets a target by restoring a tagged first version.

The child loads `/root/.lance-bench/oss.env` itself before it imports Lance or PyArrow.
The harness redacts credential values from JSON, errors, and logs.
The OSS environment file exists with mode `600`.

The no-conflict Lance smoke test passed on U, P1, and P2.
The P2 no-conflict Parquet test passed.
The P2 one-conflict stale-handle test passed.
The raw records are under `/mnt/lance/9617-bench/results`.

I recorded these OSS settings from the preflight:

- Lance uses native `oss://` on `<REDACTED_OSS_NATIVE_ENDPOINT>`.
- PyArrow uses the S3-compatible endpoint `<REDACTED_OSS_ENDPOINT>`.
- PyArrow uses virtual addressing.
- The bucket is in the same region.

## Runtime estimate

Fixture generation for Experiment 1 took 3 minutes 44 seconds.
The fixture contained the 4M-row target and all six source files.

A 1M-row calibration target with a 1 GiB Lance source took 1.11 seconds on P2 and 1.41 seconds on U.
The U replay spill was 1,106,763,720 bytes.
P1 and P2 recorded no replay spill in that run.

A 1M-row wide-table calibration run took 2.01 seconds on P2 and 2.79 seconds on P1.
Peak RSS was 4,317,740 KiB on P2 and 9,503,864 KiB on P1.

The conservative serial estimate for the written plan is below four hours.
This estimate excludes the stopped Experiment 1 run.

## Experiment status

| Experiment | Status |
|---|---|
| 1. Replay spill and no-conflict cost | Not started. Disk stop rule applied. |
| 2. One forced conflict | Not started. Disk stop rule applied. |
| 3. Partial-column update and memory cap | Not started. Disk stop rule applied. |
| 4. Object storage | Not started. Disk stop rule applied. The bucket and credentials are available. |
| 5. Constrained temp space | Not started. Disk stop rule applied. The host has no usable `/dev/loop*` device node. |
| Parquet scanner variants | Not started. No measurements are available for commit 3. |

## Commit 3 decision

I made no commit 3 decision.
The current scanner settings remain unchanged.
The benchmark produced no evidence to select variant (a) or variant (b).

## Expectations and anomalies

The disk plan was incomplete after the 54 GiB fixture existed.
The original estimate must include target replacement files and replay spill during the largest U run.
The measured write amplification from the calibration supports the 88 GiB peak estimate.

The memory-cap probe started successfully with `systemd-run --scope`.
Experiment 3 can use a 16 GiB cap after an operator fixes the disk issue.

The loop-device probe is not usable.
`losetup -a` lists no device, and `/dev/loop*` does not exist.
Experiment 5 needs an available loop device or an equivalent writable cgroup-backed filesystem.

## Five strongest numbers

These numbers come from preparation and calibration, not completed Stage 3 cells.

| Number | Exact condition |
|---:|---|
| 81,846,726,656 bytes | Initial free space on `/dev/nvme0n1`. |
| 60.98 GiB | Usable Experiment 1 budget after the 20% free-space reserve. |
| 88 GiB | Estimated peak for the 16 GiB U run with all retained sources and target replacement files. |
| 1,106,763,720 bytes | U replay spill for the 1M-row target and 1 GiB Lance source pilot. P1 and P2 recorded 0 bytes. |
| 4,317,740 KiB / 9,503,864 KiB | P2 / P1 peak RSS for the 1M-row wide-table partial update pilot. |
