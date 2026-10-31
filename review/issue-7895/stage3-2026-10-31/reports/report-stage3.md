# #9617 Stage 3 benchmark report

## Outcome

Stage 2b passed with rule (a).
U, P1, and P2 used the recorded `release` wheels from the preflight.
I rebuilt no wheel and needed no profiling wheel.

All planned local, OSS, loop-temp, cold-cache, and scanner-variant cells ran.
The repository remains clean at `9767241c21d4124dc2f8d24d642abe93c8ca859c`.
I made no commit 3 because no scanner variant met every selection condition.
I did not push and did not post GitHub comments.

A host OOM killed the first 16M P1 attempt.
I resumed with a 56 GiB P1 safety cap and preserved the OOM result.

Metrics are `median [min-max]`.
A `*` marks a metric with spread above 10%.

## Environment

| Item | Value |
|---|---|
| CPU | AMD EPYC 9T25, 16 vCPUs |
| Memory | 61 GiB |
| Swap | None |
| OS | Ubuntu 24.04.5 LTS |
| Kernel | 6.8.0-139-generic |
| Data device | `/dev/nvme0n1`, 400 GB |
| Data filesystem | ext4, 393 GiB |
| Device model | Alibaba Cloud Elastic Block Storage over NVMe |
| Python | 3.12.3 |
| Lance | 15.0.0b7 |
| PyArrow | 25.0.1 |
| NumPy | 2.5.4 |

The data volume is a whole-disk ext4 filesystem and has no partition table.
`resize2fs` grew it online from 315.9 GB to 421.6 GB.
The gate had 170.63 GiB free and an estimated peak of 88 GiB.

## Builds

The preflight build used `maturin build --release`.

| Build | Commit | Wheel SHA256 |
|---|---|---|
| U | `f9a5c662d79ac312d16d8f636cb1feba4e84aee8` | `e6b3c0b15f816027d757430cca09b7b08b92ebc0e67d905b30cd5e65ea33d6fc` |
| P1 | `15a523ffcc93e6d2c73ad2af69a1e6420efcdc22` | `28e861a077701abbbf97a924525bf6ab1d70c06674bc1bfe4874e0917294d73a` |
| P2 | `9767241c21d4124dc2f8d24d642abe93c8ca859c` | `5b9945c84d399258ebe04d7a5cad604f03d846666d76559458e0e3aa8e478e05` |

## Experiment 1

Target: 4M rows, full schema, about 12 GiB.
Sources: 1, 4, and 16 GiB, Lance and Parquet, 50% updates and 50% inserts.
Runs: 5 at 1 and 4 GiB, 3 at 16 GiB.

| Size | Source | Build | Runs | Wall s | CPU s | Peak RSS GiB | Spill GiB |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | lance | P1 | 5 | 1.249 [1.120-4.730]* | 5.141 [4.392-5.444]* | 2.662 [1.821-3.250]* | 0.000 [0.000-0.000] |
| 1 | lance | P2 | 5 | 1.275 [1.216-4.938]* | 5.283 [4.399-5.393]* | 3.219 [2.040-3.454]* | 0.000 [0.000-0.000] |
| 1 | lance | U | 5 | 1.328 [1.308-4.804]* | 5.893 [5.063-6.021]* | 3.157 [2.079-3.277]* | 1.031 [1.031-1.031] |
| 1 | parquet | P1 | 5 | 1.246 [1.236-4.887]* | 8.283 [5.496-8.486]* | 5.753 [3.326-5.952]* | 0.000 [0.000-0.000] |
| 1 | parquet | P2 | 5 | 1.252 [1.205-4.835]* | 8.208 [5.370-8.330]* | 5.667 [3.311-5.960]* | 0.000 [0.000-0.000] |
| 1 | parquet | U | 5 | 1.481 [1.450-4.899]* | 8.460 [5.972-8.740]* | 5.411 [3.759-5.613]* | 1.031 [1.031-1.031] |
| 4 | lance | P1 | 5 | 3.655 [3.616-21.293]* | 13.453 [9.918-13.905]* | 6.300 [2.769-7.066]* | 0.000 [0.000-0.000] |
| 4 | lance | P2 | 5 | 3.839 [3.667-21.164]* | 14.449 [9.752-14.695]* | 7.178 [2.744-7.630]* | 0.000 [0.000-0.000] |
| 4 | lance | U | 5 | 4.679 [4.326-31.253]* | 16.669 [12.130-17.091]* | 5.198 [2.605-5.824]* | 4.123 [4.123-4.123] |
| 4 | parquet | P1 | 5 | 4.107 [3.987-20.729]* | 25.873 [13.667-26.325]* | 14.886 [7.944-15.319]* | 0.000 [0.000-0.000] |
| 4 | parquet | P2 | 5 | 4.019 [3.988-21.727]* | 25.906 [13.696-26.294]* | 14.582 [7.669-14.783]* | 0.000 [0.000-0.000] |
| 4 | parquet | U | 5 | 5.064 [4.882-33.492]* | 28.010 [16.298-28.158]* | 13.347 [7.444-13.656]* | 4.123 [4.123-4.123] |
| 16 | lance | P1 | 3 | 139.525 [35.624-142.775]* | 33.384 [31.656-41.274]* | 5.174 [3.561-8.629]* | 0.000 [0.000-0.000] |
| 16 | lance | P2 | 3 | 68.351 [24.652-153.602]* | 43.288 [30.740-45.437]* | 11.532 [3.905-11.921]* | 0.000 [0.000-0.000] |
| 16 | lance | U | 3 | 164.522 [124.364-202.177]* | 46.354 [39.106-55.485]* | 8.842 [4.089-11.845]* | 16.492 [16.492-16.492] |
| 16 | parquet | P1 | 3 | 88.964 [86.470-93.445] | 77.814 [59.735-93.325]* | 32.277 [28.253-32.393]* | 0.000 [0.000-0.000] |
| 16 | parquet | P2 | 3 | 95.066 [84.366-106.500]* | 68.505 [60.188-78.284]* | 22.273 [21.602-33.963]* | 0.000 [0.000-0.000] |
| 16 | parquet | U | 3 | 189.369 [182.496-200.367] | 68.246 [61.976-85.795]* | 23.913 [22.796-24.643] | 16.492 [16.492-16.492] |

P1 and P2 used no replay spill in every full-schema cell.
U spilled the full source size.

### Experiment 1 plans

| Size | Source | Build | Join | Build side | Build rows | Build memory | Source plan |
|---:|---|---|---|---|---:|---:|---|
| 1 | lance | P1 | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 1 | lance | P2 | Partitioned / Right | target | 4.00 M | 0.213 GiB | LanceRead |
| 1 | lance | U | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 1 | parquet | P1 | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 1 | parquet | P2 | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 1 | parquet | U | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 4 | lance | P1 | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 4 | lance | P2 | Partitioned / Right | target | 4.00 M | 0.213 GiB | LanceRead |
| 4 | lance | U | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 4 | parquet | P1 | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 4 | parquet | P2 | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 4 | parquet | U | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 16 | lance | P1 | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 16 | lance | P2 | Partitioned / Right | target | 4.00 M | 0.213 GiB | LanceRead |
| 16 | lance | U | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 16 | parquet | P1 | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 16 | parquet | P2 | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |
| 16 | parquet | U | Partitioned / Right | target | 4.00 M | 0.213 GiB | reader factory |

The P2 full-schema Lance build side matched P1 at every size.
All three full-schema Lance plans built the target side.
The P2 check therefore passed.

### Cold cache

The 4 GiB subset dropped page caches before every run.

| Source | Build | Runs | Wall s | CPU s | Peak RSS GiB | Spill GiB |
|---|---|---:|---:|---:|---:|---:|
| lance | P1 | 3 | 22.258 [22.232-34.145]* | 9.983 [9.771-10.014] | 3.244 [2.950-3.627]* | 0.000 [0.000-0.000] |
| parquet | P1 | 3 | 22.853 [22.774-22.894] | 13.569 [13.510-13.992] | 8.271 [8.051-8.570] | 0.000 [0.000-0.000] |
| lance | P2 | 3 | 22.254 [22.208-34.872]* | 9.857 [9.756-9.952] | 3.442 [3.419-3.541] | 0.000 [0.000-0.000] |
| parquet | P2 | 3 | 35.785 [35.090-35.836] | 13.958 [13.958-14.029] | 8.063 [7.871-8.409] | 0.000 [0.000-0.000] |
| lance | U | 3 | 36.007 [35.312-37.483] | 12.230 [11.990-12.383] | 3.173 [3.128-4.064]* | 4.123 [4.123-4.123] |
| parquet | U | 3 | 35.015 [34.314-36.076] | 16.215 [16.062-16.302] | 8.320 [8.099-8.424] | 4.123 [4.123-4.123] |

## Experiment 2

Each run made one competing target update before the stale-handle merge.
Use CPU and peak RSS for conflict comparisons.
Wall time includes randomized retry backoff and is informational.

| Size | Source | Build | Runs | Wall s | CPU s | Peak RSS GiB | Spill GiB |
|---:|---|---|---:|---:|---:|---:|---:|
| 4 | lance | P1 | 3 | 12.277 [7.481-49.538]* | 24.311 [21.021-24.956]* | 8.095 [6.466-8.119]* | 0.000 [0.000-0.000] |
| 4 | lance | P2 | 3 | 21.174 [12.261-21.834]* | 25.909 [25.438-26.073] | 7.717 [7.036-9.346]* | 0.000 [0.000-0.000] |
| 4 | lance | U | 3 | 19.134 [8.419-35.499]* | 24.358 [20.404-24.591]* | 6.258 [5.211-7.148]* | 4.123 [4.123-4.123] |
| 4 | parquet | P1 | 3 | 22.659 [13.089-51.739]* | 48.726 [37.604-49.407]* | 17.303 [16.830-18.718]* | 0.000 [0.000-0.000] |
| 4 | parquet | P2 | 3 | 22.967 [17.772-23.068]* | 49.719 [48.352-49.993] | 17.668 [17.310-18.073] | 0.000 [0.000-0.000] |
| 4 | parquet | U | 3 | 26.479 [19.511-157.474]* | 35.337 [23.537-35.420]* | 13.741 [7.579-14.136]* | 4.123 [4.123-4.123] |
| 16 | lance | P1 | 3 | 312.327 [180.085-363.092]* | 71.197 [70.737-79.536]* | 9.347 [9.081-10.721]* | 0.000 [0.000-0.000] |
| 16 | lance | P2 | 3 | 96.752 [48.362-138.675]* | 85.039 [82.903-86.882] | 12.416 [11.769-13.597]* | 0.000 [0.000-0.000] |
| 16 | lance | U | 3 | 469.521 [436.129-548.601]* | 77.167 [77.126-80.263] | 11.705 [9.897-12.793]* | 16.492 [16.492-16.492] |
| 16 | parquet | P1 | 3 | 473.670 [326.576-545.131]* | 152.096 [110.246-175.206]* | 29.590 [23.678-35.964]* | 0.000 [0.000-0.000] |
| 16 | parquet | P2 | 3 | 381.805 [279.393-472.299]* | 151.437 [137.897-173.880]* | 33.293 [29.168-38.349]* | 0.000 [0.000-0.000] |
| 16 | parquet | U | 3 | 461.938 [332.151-904.953]* | 89.374 [84.993-89.712] | 21.411 [21.373-22.963] | 16.492 [16.492-16.492] |

All 36 cells completed after I increased the artificial retry window from 30 seconds to 30 minutes.
The original 30-second and 10-minute harness limits expired before valid 16 GiB retries completed.

### Noise floor

Experiment 2 used the same Parquet path for P1 and P2 at 16 GiB.

| Build | Wall s | CPU s | Peak RSS GiB |
|---|---:|---:|---:|
| P1 | 473.670 [326.576-545.131] | 152.096 [110.246-175.206] | 29.590 [23.678-35.964] |
| P2 | 381.805 [279.393-472.299] | 151.437 [137.897-173.880] | 33.293 [29.168-38.349] |

The P1/P2 median differences were 91.865 s wall, 3.702 GiB RSS, and 0.659 s CPU.
These are 21.5%, 11.8%, and 0.4% of the mean values.
The ranges overlap, so these differences are noise.

For hot-cache 16 GiB cells, assume about 35% wall noise, 30% CPU noise, and 25% RSS noise.
Use cold-cache runs for decisions near those bands.

## Experiment 3

The source has 100K matching partial rows.
The target uses Auto write mode, which selected RewriteRows.

| Rows | Build | Condition | Runs OK | Wall s | CPU s | Peak RSS GiB | Build side | Build memory |
|---:|---|---|---:|---:|---:|---:|---|---:|
| 1,000,000 | P1 | uncapped | 3/3 | 2.761 [2.680-2.912] | 9.941 [9.751-10.280] | 9.126 [9.116-10.663]* | target | 2.887 GiB |
| 1,000,000 | P2 | uncapped | 3/3 | 2.078 [2.045-2.172] | 6.881 [6.791-7.215] | 4.807 [4.239-4.853]* | source | 0.005 GiB |
| 1,000,000 | U | uncapped | 3/3 | 2.749 [2.658-2.791] | 9.873 [9.779-10.218] | 8.608 [8.222-9.747]* | target | 2.887 GiB |
| 4,000,000 | P1 | uncapped | 3/3 | 9.262 [8.983-9.319] | 32.744 [30.771-34.857]* | 29.143 [28.284-29.237] | target | 11.548 GiB |
| 4,000,000 | P2 | uncapped | 3/3 | 6.712 [6.462-7.063] | 19.270 [19.064-19.616] | 5.334 [5.312-6.797]* | source | 0.005 GiB |
| 4,000,000 | U | uncapped | 3/3 | 9.171 [9.152-9.328] | 32.447 [32.022-36.192]* | 27.819 [27.211-28.168] | target | 11.548 GiB |
| 8,000,000 | P1 | uncapped | 3/3 | 18.130 [18.055-86.428]* | 66.979 [55.680-71.665]* | 49.774 [49.054-52.050] | target | 23.283 GiB |
| 8,000,000 | P2 | uncapped | 3/3 | 12.220 [12.112-78.378]* | 33.035 [26.443-33.382]* | 7.168 [6.677-8.092]* | source | 0.005 GiB |
| 16,000,000 | P1 | 56 GiB safety cap | 0/3 | OOM | OOM | OOM | OOM before plan | unavailable |
| 16,000,000 | P2 | uncapped | 3/3 | 252.936 [23.719-253.876]* | 37.902 [35.398-62.421]* | 4.998 [4.796-8.086]* | source | 0.005 GiB |

| Rows | Build | Cap | Runs OK | Wall s | CPU s | Peak RSS GiB |
|---:|---|---:|---:|---:|---:|---:|
| 1,000,000 | P1 | 16 GiB | 3/3 | 2.685 [2.679-2.824] | 9.961 [9.758-10.307] | 8.804 [8.776-10.254]* |
| 1,000,000 | P2 | 16 GiB | 3/3 | 2.028 [2.013-2.338]* | 7.162 [6.940-7.443] | 4.648 [4.446-4.747] |
| 4,000,000 | P1 | 16 GiB | 0/3 | OOM | OOM | OOM |
| 4,000,000 | P2 | 16 GiB | 3/3 | 6.802 [6.632-6.839] | 20.289 [18.355-20.318] | 7.660 [6.621-7.786]* |

The smallest P1 OOM is 4M rows under the 16 GiB cap.
All three P1 attempts exited with code 137.
P2 completed all three 4M attempts with a median peak RSS of 8.23 GiB.

P1 `analyze_plan` at 16M rows also exceeded a 56 GiB safety cap.
P2 used the source side, 100K build rows, and about 0.005 GiB of build memory at every size.
The 16M P1 target build requires about 50 GiB before other allocations.

## Full-schema Lance follow-up

P1 uses one `StreamingTableExec` source partition.
P2 uses a native `LanceRead` over six fragments.
Both plans emit 676 source batches before the 16-way hash repartition.
The plans do not expose a different batch size or readahead setting.

| Cache | Build | Wall s | CPU s | Peak RSS GiB | Read GiB/s |
|---|---|---|---:|---:|---:|
| Hot | P1 | 25.330 [24.379-61.516] | 41.440 [38.439-42.401] | 9.231 [8.741-10.717] | cached |
| Hot | P2 | 30.978 [25.971-43.879] | 44.229 [43.954-45.258] | 11.936 [11.429-12.694] | cached |
| Hot | P2, 64 MiB bound | 25.831 [25.481-25.866] | 44.492 [43.828-44.668] | 10.263 [9.649-11.588] | cached |
| Cold | P1 | 161.927 [159.939-164.719] | 30.429 [30.147-30.801] | 3.553 [3.437-3.648] | 0.0978 [0.0969-0.0998] |
| Cold | P2 | 165.444 [163.619-165.730] | 30.638 [30.209-30.933] | 4.881 [3.574-4.954] | 0.0965 [0.0963-0.0975] |
| Cold | P2, 64 MiB bound | 165.200 [163.945-165.436] | 30.286 [30.155-30.395] | 3.894 [3.511-4.105] | 0.0967 [0.0965-0.0974] |

The cold runs read 15.96 GiB from the backing device in every build.
They used the same disk throughput and CPU time within about 3%.

The evidence rejects the hypothesis.
The native path can issue fragment reads with more concurrency, but the measured backing-device throughput did not increase.
The earlier 139 s versus 68 s result did not reproduce.
The follow-up hot medians were 25.33 s for P1 and 30.98 s for P2.

I built one local, uncommitted P2 variant with `with_batch_size_bytes(64 MiB)`.
The patch is `/mnt/lance/9617-bench/followup/patches/native-source-64mib.patch`.
The wheel SHA256 is `60a1f1e3f69df937c5f7f7d94f54136b047f39751b8d8b93b188fef930adc539`.
The PR tree is clean again.

At cold cache, the bound recovered 74% of the P2-to-P1 RSS gap.
The P2-to-P1 gap fell from 1.328 GiB to 0.341 GiB.
Wall time changed by 0.15% versus P2 and stayed within 2.1% of P1.
CPU and disk throughput stayed within 1% and 2%.

## Upstream retry default

U used the default 10 retries and 30-second retry timeout.
The 16 GiB Lance source received one forced competing update.

The first attempt took 115.217 s.
It wrote a 16.492 GiB replay spill.
It returned `retry_timeout` after attempted 1 time.
U did not start a second attempt.
Peak RSS was 9.252 GiB and CPU time was 52.103 s.

## Experiment 4

OSS used Lance native `oss://` on the internal endpoint.
PyArrow used the S3-compatible internal endpoint with virtual addressing.
All children loaded `/root/.lance-bench/oss.env` themselves.
Credentials did not appear in logs or JSON.

| Source | Build | Conflict | Runs | Wall s | CPU s | Peak RSS GiB | Spill GiB | Received GB |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 4gib-lance | P2 | no | 3/3 | 7.111 [6.965-7.648] | 26.697 [26.209-26.833] | 6.756 [5.732-7.293]* | 0.000 [0.000-0.000] | 4.483 [4.483-4.484] |
| 4gib-lance | P2 | yes | 3/3 | 36.791 [22.120-37.071]* | 48.607 [47.580-50.542] | 7.857 [6.689-8.112]* | 0.000 [0.000-0.000] | 8.963 [8.962-8.966] |
| 4gib-lance | U | no | 3/3 | 7.620 [6.940-8.050]* | 29.720 [29.475-29.764] | 5.873 [5.007-5.918]* | 4.123 [4.123-4.123] | 4.482 [4.482-4.483] |
| 4gib-lance | U | yes | 3/3 | 21.418 [14.157-29.724]* | 40.172 [39.477-40.280] | 5.681 [5.055-6.021]* | 4.123 [4.123-4.123] | 4.497 [4.497-4.497] |
| 4gib-parquet | P2 | no | 3/3 | 6.148 [6.034-7.226]* | 28.490 [27.471-28.666] | 11.192 [10.910-11.380] | 0.000 [0.000-0.000] | 4.596 [4.596-4.597] |
| 4gib-parquet | P2 | yes | 3/3 | 18.735 [18.680-33.836]* | 56.000 [54.222-56.071] | 11.519 [11.470-12.382] | 0.000 [0.000-0.000] | 9.194 [9.194-9.194] |
| 4gib-parquet | U | no | 3/3 | 6.529 [6.509-6.642] | 33.296 [32.812-33.999] | 9.683 [9.525-9.886] | 4.123 [4.123-4.123] | 4.596 [4.596-4.601] |
| 4gib-parquet | U | yes | 3/3 | 32.078 [19.811-35.031]* | 41.375 [40.569-41.395] | 9.767 [9.404-11.276]* | 4.123 [4.123-4.123] | 4.612 [4.611-4.619] |

All 24 OSS cells completed.
I removed the 16 uploaded files after the experiment.

## Experiment 5

`modprobe loop` created usable loop devices.
I mounted `TMPDIR` as a 4 GiB ext4 filesystem on `/dev/loop0`.
I did not use a memory cap for this experiment.

| Source GiB | Build | Runs OK | Wall s | CPU s | Peak RSS GiB | Spill peak GiB | Result |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | P2 | 3/3 | 1.205 [1.186-1.247] | 5.253 [5.216-5.277] | 3.558 [3.468-3.693] | 0.000 [0.000-0.000] | success |
| 1 | U | 3/3 | 1.350 [1.276-5.321]* | 5.898 [4.729-6.022]* | 3.246 [2.107-3.291]* | 1.031 [1.031-1.031] | success |
| 4 | P2 | 3/3 | 3.607 [3.531-3.777] | 13.460 [13.080-14.122] | 5.583 [5.195-7.198]* | 0.000 [0.000-0.000] | success |
| 4 | U | 0/3 | failed | failed | failed | 3.843 [3.843-3.843] | ENOSPC |
| 16 | P2 | 3/3 | 24.599 [19.660-144.470]* | 44.226 [33.630-44.663]* | 10.173 [6.401-10.918]* | 0.000 [0.000-0.000] | success |
| 16 | U | 0/3 | failed | failed | failed | 3.843 [3.843-3.843] | ENOSPC |

U failed all 4 and 16 GiB cells with ENOSPC.
P2 completed all cells with zero replay spill.

## Parquet scan parameters

The variants were local, uncommitted monkey patches in the child process.
The harness measured the current and variant settings three times per condition.

| Size | Conflict | Setting | Peak RSS GiB | Wall s | CPU s | Qualifies |
|---:|---|---|---:|---:|---:|---|
| 4 | no | current | 14.582 [7.669-14.783]* | 4.019 [3.988-21.727]* | 25.906 [13.696-26.294]* |  |
| 4 | no | U reference | 13.347 [7.444-13.656]* | 5.064 [4.882-33.492]* | 28.010 [16.298-28.158]* |  |
| 4 | no | a: readahead=1 | 11.642 [11.377-11.693] | 3.918 [3.901-3.990] | 24.547 [24.072-24.581] | yes |
| 4 | no | b: 64 MiB budget | 10.173 [10.014-10.330] | 3.792 [3.784-3.845] | 16.813 [16.678-16.846] | yes |
| 4 | yes | current | 17.668 [17.310-18.073] | 22.967 [17.772-23.068]* | 49.719 [48.352-49.993] |  |
| 4 | yes | U reference | 13.741 [7.579-14.136]* | 26.479 [19.511-157.474]* | 35.337 [23.537-35.420]* |  |
| 4 | yes | a: readahead=1 | 13.986 [13.718-14.305] | 13.183 [8.323-22.774]* | 47.002 [46.669-47.450] | no |
| 4 | yes | b: 64 MiB budget | 12.830 [12.595-14.555]* | 17.339 [8.018-22.197]* | 31.578 [31.543-31.963] | yes |
| 16 | no | current | 22.273 [21.602-33.963]* | 95.066 [84.366-106.500]* | 68.505 [60.188-78.284]* |  |
| 16 | no | U reference | 23.913 [22.796-24.643] | 189.369 [182.496-200.367] | 68.246 [61.976-85.795]* |  |
| 16 | no | a: readahead=1 | 24.644 [21.659-27.116]* | 72.477 [67.325-174.941]* | 72.664 [50.963-79.247]* | no |
| 16 | no | b: 64 MiB budget | 20.761 [20.525-22.884]* | 154.931 [59.843-172.827]* | 48.721 [47.508-54.660]* | no |
| 16 | yes | current | 33.293 [29.168-38.349]* | 381.805 [279.393-472.299]* | 151.437 [137.897-173.880]* |  |
| 16 | yes | U reference | 21.411 [21.373-22.963] | 461.938 [332.151-904.953]* | 89.374 [84.993-89.712] |  |
| 16 | yes | a: readahead=1 | 28.346 [22.188-32.992]* | 156.152 [106.654-504.992]* | 144.870 [98.404-173.627]* | no |
| 16 | yes | b: 64 MiB budget | 24.962 [22.923-28.887]* | 226.297 [116.609-530.349]* | 101.632 [96.894-105.509] | no |

Variant (a) failed RSS at 4 GiB conflict and both 16 GiB cases.
It also exceeded the 5% CPU limit at 16 GiB no conflict.
Variant (b) failed the 5% wall-time limit at 16 GiB no conflict.
It also failed the U RSS limit at 16 GiB conflict.

No variant qualifies.
I kept the current scanner settings and made no commit 3.

## Contradictions and findings

The no-conflict full-schema hardware was not stable across repetitions.
Many wall, RSS, and CPU spreads exceed 10%.
The first run in several cells was much slower than later runs.
The cold-cache subset was more stable than the hot-cache subset.

Parquet did not behave as a P1/P2 control.
The current P2 Parquet source exceeded U RSS in three of four measured conditions.
It stayed below U only at 16 GiB without a conflict.
Variant (b) improves that peak but does not satisfy every case.

P2's native source removes replay spill and sharply lowers partial-update memory.
At 8M wide rows, P1 used 49.77 GiB RSS and P2 used 7.17 GiB.

P1 can OOM even without the requested 16 GiB cap.
At 16M rows it exceeded the 56 GiB safety cap in all three normal attempts.

## Five strongest numbers

| Number | Exact condition |
|---:|---|
| 16.49 GiB | U replay spill, 16 GiB Lance source, no conflict, 4M target. |
| 49.77 GiB vs 7.17 GiB | P1 vs P2 median peak RSS, 8M wide target, 100K matching rows, auto RewriteRows. |
| 4M | Smallest P1 OOM with a 16 GiB cap. P2 completed all three attempts. |
| 3.84 GiB | U peak spill before ENOSPC on the 4 GiB loop filesystem. P2 used 0 bytes. |
| 154.93 s vs 95.07 s | Variant (b) vs current wall time, 16 GiB Parquet source, no conflict. The 5% limit failed. |

## Raw data

Raw JSON, plans, and logs are under `/mnt/lance/9617-bench/results`, `/mnt/lance/9617-bench/plans`, and `/mnt/lance/9617-bench/logs`.
