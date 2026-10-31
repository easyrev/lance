# Stage 3 follow-up report

## Unit correction

All memory and spill values now use GiB.
Network values use decimal GB.

The corrected strongest values are:

| Corrected value | Condition |
|---|---|
| 16.49 GiB | U replay spill for the 16 GiB Lance source |
| 49.77 GiB vs 7.17 GiB | P1 vs P2 peak RSS for the 8M-row wide target |
| 3.84 GiB | U spill before ENOSPC on the 4 GiB loop filesystem |

## Conflict comparisons

Experiment 2 comparisons use CPU time and peak RSS.
Wall time remains informational because the retry policy randomizes backoff.

At 16 GiB Parquet, P1 and P2 use the same path:

| Build | Wall s | CPU s | Peak RSS GiB |
|---|---:|---:|---:|
| P1 | 473.670 [326.576-545.131] | 152.096 [110.246-175.206] | 29.590 [23.678-35.964] |
| P2 | 381.805 [279.393-472.299] | 151.437 [137.897-173.880] | 33.293 [29.168-38.349] |

The median differences are 91.865 s wall, 0.659 s CPU, and 3.702 GiB RSS.
These are 21.5%, 0.4%, and 11.8% of the mean values.
The ranges overlap.

For hot-cache 16 GiB cells, assume about 35% wall noise, 30% CPU noise, and 25% RSS noise.
Use cold-cache measurements for decisions near those bands.

## Native Lance source memory

The Python scanner and `LanceTableProvider` resolve the same scan settings.

| Setting | Python effective | Native effective |
|---|---:|---:|
| Row batch size | 8,192 | 8,192 |
| Byte batch size | `None` | `None` |
| I/O buffer | 2 GiB | 2 GiB |
| Fragment readahead | 16 | 16 |
| Batch readahead | 14 | 14 |
| Scan order | Ordered | Ordered |

The source plans show:

| Build | Source node | Source batches | Repartition fetch time |
|---|---|---:|---:|
| P1 | `StreamingTableExec` | 676 | 1.56 s |
| P2 | `LanceRead` | 676 | 14.62 s |

The default scan settings do not differ.
The extra RSS appears above the scan boundary in DataFusion exchange buffering.

Cold-cache measurements reject an I/O throughput explanation:

| Build | Backing read | Read throughput | CPU |
|---|---:|---:|---:|
| P1 | 15.96 GiB | 0.0978 GiB/s | 30.429 s |
| P2 | 15.96 GiB | 0.0965 GiB/s | 30.638 s |

## Unadopted native bound

A local patch set `with_batch_size_bytes(64 MiB)` on the native source.
The patch and the resulting wheel remain unadopted.

| Cache | Build | Wall s | CPU s | Peak RSS GiB | Read GiB/s |
|---|---|---|---:|---:|---:|
| Cold | P1 | 161.927 | 30.429 | 3.553 | 0.0978 |
| Cold | P2 | 165.444 | 30.638 | 4.881 | 0.0965 |
| Cold | P2 with 64 MiB bound | 165.200 | 30.286 | 3.894 | 0.0967 |

The bound recovered 74% of the P2-to-P1 RSS gap.
Wall time changed by 0.15% versus P2 and stayed within 2.1% of P1.
CPU time and read throughput stayed within 1% and 2%.

The patch SHA256 is:
`1db993fa68b55f17261c690aae74fb5825db2bd133f0eaa375e4c4495cc4ede9`

The wheel SHA256 is:
`60a1f1e3f69df937c5f7f7d94f54136b047f39751b8d8b93b188fef930adc539`

The wheel is not included.

## Upstream retry default

U used the default 10 retries and 30-second timeout.
One competing update changed the target after U opened its handle.

| Metric | Result |
|---|---|
| First attempt | 115.217 s |
| Replay spill | 16.492 GiB |
| Peak RSS | 9.252 GiB |
| CPU | 52.103 s |
| Attempts | 1 |
| Result | `retry_timeout` |

U did not start a second attempt.
The timeout check occurs after the first commit conflict and before backoff.

## Evidence boundary

Benchmarks used the preflight `release` wheels.
I adopted no benchmark code change.
I did not change PR code for this follow-up.
