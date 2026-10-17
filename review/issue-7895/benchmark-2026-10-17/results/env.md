# PR #9617 scaling benchmark environment

Benchmark date: 2026-10-17 (Asia/Shanghai)

## Host

- Cloud: Alibaba Cloud ECS, Shanghai
- Instance type: `ecs.i4r.4xlarge`
- Virtualization: KVM
- OS: Ubuntu 24.04.5 LTS
- Kernel: `6.8.0-139-generic`
- Architecture: `x86_64`
- CPU: Intel Xeon Platinum 8369B at 2.70 GHz
- CPU topology: 16 vCPU, 1 socket, 8 cores, 2 threads per core
- Memory: 128 GiB nominal, 123 GiB visible to the guest
- Swap: disabled

## Storage

- Benchmark filesystem: Alibaba NVMe controller, 959.9 GB (894.0 GiB) raw device, ext4 mounted at `/mnt/lance` (879 GiB filesystem, rotational flag 0)
- Disk use after the run: 185 GiB / 879 GiB (23%)
- Restricted-TMP test: a 2 GiB ext4 loop device mounted at `/mnt/lance/bench-9617/smalltmp`; it was not tmpfs
- The benchmark used one fresh per-run directory under `TMPDIR`. Its allocated blocks were polled every 50 ms.

## Revisions and builds

| Build | Commit | Notes |
|---|---|---|
| upstream | `dc53d5d174af62c49ddd98d1024a64488c1e4404` | `lance-format/lance` main at benchmark start and report finalization |
| original PR head | `ff576648ac969f0379400748c987c29d986a288f` | `refs/pull/9617/head` and `easyrev/lance:feat/7895-rescannable-sources` |
| rebased PR | `e18df5f4708b42be99aa33ec9ac12de15401982f` | PR patch rebased onto the upstream commit above |

The original and rebased PR commits have the same stable patch ID, `12bf58d204d22624576c3e68b2cbfa0917cd3e33`. The rebased PR commit has the upstream commit as its parent. Both worktrees were clean when built and after the benchmark.

- Cargo profile: `release-with-debug`
- Builds: separate target directories and separate virtual environments (`venv-upstream`, `venv-pr`)
- Rust: `rustc 1.98.1 (48a229cea 2026-09-01)`, LLVM 22.1.8
- Cargo: 1.98.1
- Python: 3.12.3
- PyArrow: 25.0.1
- Lance Python package version: 14.0.0-beta.19
- PyArrow default memory-pool backend: mimalloc

## Profilers

- `perf` 6.8.12
- `heaptrack` 1.5.0
- `kernel.perf_event_paranoid=4`; hardware cycle/instruction counters were unavailable. Profiles therefore used the software `cpu-clock` event and flat symbol attribution.

## Dataset

- Target: 4,000,000 rows, 16 fragments, approximately 12 GiB, with no `id` index for the DataFusion main path. A second tagged base carried the BTREE index for the legacy-path check.
- Schema: `id: int64`, `vec: fixed_size_list<float32, 768>`, approximately 32-byte `label`, and `ts: timestamp`.
- Each source had deterministic values and a 50/50 split between existing and new keys. Lance and Parquet encodings were generated once and shared by both builds.

| Tier | Rows | Logical Arrow bytes |
|---|---:|---:|
| 128 MiB | 42,963 | 134,216,412 |
| 1 GiB | 343,707 | 1,073,740,668 |
| 4 GiB | 1,374,829 | 4,294,965,796 |
| 16 GiB | 5,499,318 | 17,179,869,432 |

## Result integrity

- `raw.jsonl`: 288 records, SHA-256 `3e96fc039eec46f3541bd5288acd2fa4017d06d6169c05c0620005b44a5a4d8e`
- Successful runs: 287; each passed row-count, version-count, and 81-row all-column sample verification
- Expected failure: one upstream restricted-TMP run, ending with `ENOSPC`
- Final target state: 4,000,000 rows, 16 fragments, restored to the pristine base contents
