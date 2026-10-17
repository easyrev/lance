# Issue 7895 local performance evidence

Base: `4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9`. Candidate: `26632629ca162cdbfd82dabad1d80e3e6c92b364`.

Both snapshots use `release-with-debug`. Debug-section removal preserves the loaded ELF sections, as recorded in the snapshot receipts.

The matrix contains 120 measurements: two fixtures, three input types, two conflict conditions, two snapshots, and five repetitions.
Each source has a seeded binary payload. The target has one matching row. The merge updates that row and inserts all other keys.
Source files are read before timing. Each observation uses a fresh process. Baseline and candidate order alternate across repetitions.
Timing includes merge execution and the concurrent update when present. It excludes fixture preparation, cache warming, and correctness checks.

Conflict wall time includes randomized retry backoff. The first failure selects 0–3 slots, each approximately 1.1 times the first attempt duration.
Paired trials do not share a random slot. Their wall-time ratios cannot isolate replay cost, and five samples can retain substantial variation.

## Eligible inputs

| Fixture | Source | Conflict | Baseline ms, median [min, max] | Candidate ms, median [min, max] | Change | RSS MiB, baseline → candidate | Replay dirs, baseline → candidate | Spill MiB, baseline → candidate |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 1.125 MiB | lance | no | 9.28 [8.23, 12.39] | 11.93 [10.55, 13.96] | +28.6% | 227.5 → 228.2 | 1 → 0 | 0.00 → 0.00 |
| 1.125 MiB | lance | yes | 102.60 [78.57, 113.18] | 80.87 [37.72, 106.70] | -21.2% | 236.0 → 239.1 | 1 → 0 | 0.00 → 0.00 |
| 1.125 MiB | arrow | no | 11.27 [10.20, 11.64] | 10.64 [10.55, 12.18] | -5.6% | 233.8 → 234.7 | 1 → 0 | 0.00 → 0.00 |
| 1.125 MiB | arrow | yes | 66.48 [30.34, 90.64] | 70.66 [54.64, 90.36] | +6.3% | 243.9 → 247.0 | 1 → 0 | 0.00 → 0.00 |
| 132 MiB | lance | no | 230.82 [223.10, 250.03] | 218.17 [183.08, 224.06] | -5.5% | 543.2 → 434.9 | 1 → 0 | 132.10 → 0.00 |
| 132 MiB | lance | yes | 813.29 [368.65, 893.65] | 982.04 [364.59, 1060.94] | +20.7% | 570.1 → 609.1 | 1 → 0 | 132.10 → 0.00 |
| 132 MiB | arrow | no | 201.76 [182.70, 230.44] | 193.26 [172.10, 219.33] | -4.2% | 747.3 → 631.9 | 1 → 0 | 132.11 → 0.00 |
| 132 MiB | arrow | yes | 390.78 [328.71, 1195.51] | 834.62 [375.00, 1160.65] | +113.6% | 810.4 → 738.4 | 1 → 0 | 132.11 → 0.00 |

## Opaque Scanner fallback

These observations measure the conservative fallback. They are separate from inputs eligible for the replay optimization.

| Fixture | Source | Conflict | Baseline ms, median [min, max] | Candidate ms, median [min, max] | Change | RSS MiB, baseline → candidate | Replay dirs, baseline → candidate | Spill MiB, baseline → candidate |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 1.125 MiB | scanner | no | 10.96 [10.01, 11.79] | 10.52 [10.06, 12.63] | -4.0% | 240.5 → 234.7 | 1 → 1 | 0.00 → 0.00 |
| 1.125 MiB | scanner | yes | 56.52 [37.93, 123.43] | 79.13 [56.39, 122.55] | +40.0% | 246.1 → 244.3 | 1 → 1 | 0.00 → 0.00 |
| 132 MiB | scanner | no | 205.86 [191.43, 212.39] | 212.27 [197.51, 242.80] | +3.1% | 719.3 → 742.9 | 1 → 1 | 132.11 → 132.11 |
| 132 MiB | scanner | yes | 739.05 [561.87, 1237.32] | 840.64 [408.04, 972.00] | +13.7% | 790.5 → 792.0 | 1 → 1 | 132.11 → 132.11 |

## Conflict execution before backoff and total CPU

The first commit hook time ends before the injected update and retry backoff. It still includes scheduling and all preceding first-attempt work.
Total CPU is process user plus system time across both attempts, commits, and the concurrent update. It excludes time spent sleeping.
The following cells show medians and ranges. First-hook CPU shows medians. Scanner remains the fallback control.

| Fixture | Source | First commit hook ms, baseline | First commit hook ms, candidate | Total CPU ms, baseline | Total CPU ms, candidate | First hook CPU ms, baseline → candidate |
|---|---|---:|---:|---:|---:|---:|
| 1.125 MiB | lance | 9.53 [8.83, 10.70] | 13.23 [11.41, 17.26] | 28.28 [26.37, 34.16] | 31.72 [29.05, 42.03] | 14.11 → 15.23 |
| 1.125 MiB | arrow | 9.62 [7.87, 10.23] | 10.68 [9.70, 11.45] | 28.91 [27.19, 35.57] | 32.31 [28.16, 32.38] | 13.62 → 14.19 |
| 1.125 MiB | scanner | 11.22 [10.48, 15.30] | 9.46 [7.84, 11.08] | 34.71 [30.55, 37.02] | 30.19 [25.07, 33.42] | 16.50 → 13.77 |
| 132 MiB | lance | 219.61 [213.95, 302.52] | 197.44 [175.83, 232.76] | 685.11 [646.64, 916.90] | 732.02 [675.72, 840.58] | 492.54 → 391.24 |
| 132 MiB | arrow | 196.74 [178.96, 224.42] | 200.80 [186.03, 210.67] | 649.66 [600.65, 731.99] | 648.48 [641.98, 691.57] | 405.82 → 350.95 |
| 132 MiB | scanner | 216.45 [188.91, 252.92] | 203.92 [191.64, 220.70] | 659.59 [636.98, 725.16] | 660.65 [627.05, 685.53] | 425.72 → 421.23 |

## Plans and attribution

- `benchmark-fixture-small/lance`: normalized topology matches.
- `benchmark-fixture-small/arrow`: normalized topology matches.
- `benchmark-fixture-small/scanner`: normalized topology matches.
- `benchmark-fixture/lance`: normalized topology matches.
- `benchmark-fixture/arrow`: normalized topology matches.
- `benchmark-fixture/scanner`: normalized topology matches.

Raw `analyze_plan` files include runtime counters. The script verifies unchanged target versions and data after each plan capture.
Topology comparison preserves operators and join settings. It does not establish equality of every optimizer estimate.
Both implementations use StreamingTable providers. The replay detector distinguishes their source behavior even when the displayed operators match.
The 14 controls passed against these exact binary hashes. They include in-memory replay, materialized input, opaque Scanner fallback, and zero-retry failure.

The following list retains every higher candidate median without a significance claim:

- `benchmark-fixture-small/lance/clean`: +28.6%, paired median ratio 1.211.
- `benchmark-fixture-small/arrow/conflict`: +6.3%, paired median ratio 1.071.
- `benchmark-fixture-small/scanner/conflict`: +40.0%, paired median ratio 1.444.
- `benchmark-fixture/lance/conflict`: +20.7%, paired median ratio 1.305.
- `benchmark-fixture/arrow/conflict`: +113.6%, paired median ratio 1.364.
- `benchmark-fixture/scanner/clean`: +3.1%, paired median ratio 1.109.
- `benchmark-fixture/scanner/conflict`: +13.7%, paired median ratio 1.144.

## Assessment of observed changes

The verified benefit is removal of replay storage for eligible sources. Every eligible candidate sample created zero replay directories, while baseline created one.

This holds below the spill threshold. The positive one-shot control still created a replay directory for the 256-byte source without a disk file.

For the 132 MiB source, each eligible baseline merge created a 132.10–132.11 MiB replay file. Each eligible candidate merge avoided that file.

Without conflict, median elapsed time fell 5.5% for LanceDataset and 4.2% for Arrow Dataset. Median process RSS fell about 108 and 115 MiB respectively.

The time ranges overlap. These observations support lower temporary storage and modest measured latency changes, not a general speed guarantee.

### Small LanceDataset latency

The primary clean run increased from 9.28 to 11.93 ms. Total CPU stayed approximately flat, at 13.78 versus 13.61 ms.

A separate follow-up disabled `LD_PRELOAD` entirely. It retained ten alternating baseline/candidate pairs with the same fixture and binary hashes.

The follow-up medians were 11.20 and 11.95 ms, an increase of 0.75 ms or 6.7%. Their ranges were 8.80–14.52 and 10.39–13.37 ms.

Follow-up CPU medians were 15.90 and 13.86 ms. The smaller latency difference and overlapping ranges do not establish a fixed 2.65 ms overhead.

They also do not demonstrate a latency benefit for small LanceDataset sources.

Source inspection shows that the candidate opens its reader factory on a blocking worker. Extra scheduling is a possible cost, not an established cause.

These measurements do not isolate scheduler, allocator, or generated-code effects. The candidate's small-input latency cost therefore remains a measured tradeoff with uncertain attribution.

The original 120 samples remain unchanged. The additional 20 observations are separate in `no-probe-followup/` and `no-probe-followup-summary.json`.

### Conflict cases with higher candidate medians

- Small Arrow Dataset wall time increased 6.3%, from 66.48 to 70.66 ms. First-hook time rose 9.62→10.68 ms, and CPU rose 28.91→32.31 ms. CPU ranges overlap. The candidate rescans the source, whereas the baseline reuses its in-memory replay. This case shows no measured retry benefit.
- Large LanceDataset wall time increased 20.7%, from 813.29 to 982.04 ms. First-hook time fell 219.61→197.44 ms, but total CPU rose 685.11→732.02 ms. Median RSS rose 570.1→609.1 MiB. These measured costs remain part of the result despite removal of replay storage. Rescanning and allocator retention can affect retry cost, but this experiment does not isolate their individual contributions.
- Large Arrow Dataset wall time increased 113.6%, from 390.78 to 834.62 ms. First-hook time was similar, at 196.74 versus 200.80 ms. Total CPU was also similar, at 649.66 versus 648.48 ms. Wall-time ranges overlap broadly: 328.71–1195.51 versus 375.00–1160.65 ms. These samples do not establish a twofold processing slowdown. Random backoff remains a material confounder, and the exact waits were not measured.

All conflict samples completed exactly two merge commit hooks with the expected row statistics. No unexpected extra commit hooks were recorded.

Even the small LanceDataset conflict case used more median CPU, despite its lower median wall time. We therefore make no general retry-latency claim.

### Plans, I/O, and fallback variation

All six normalized plan pairs match. Raw plans also match join input counts: one target row in one batch for every case.

Small LanceDataset supplies one source batch. Small Arrow Dataset and Scanner supply two. Every large-source plan supplies 32 batches in both snapshots.

Thus, these plan captures show no join-direction or batch-count explanation for the latency differences. They do not rule out scheduling or allocation differences.

For large eligible merges, logical `wchar` fell by approximately 132.1 MiB per trial, with or without conflict. This agrees with the avoided replay file.

Large retry `rchar` also fell: approximately 392.8→257.1 MiB for LanceDataset and 395.2→261.6 MiB for Arrow Dataset.

For small retry inputs, `rchar` instead rose approximately 1.02→2.04 MiB and 1.15→2.24 MiB. The candidate rereads source data that baseline retains in memory.

These are process I/O counters, not physical storage traffic. Cancelled writes and warm caches prevent a direct physical-I/O claim.

Opaque Scanner retains replay in every sample. Its conflict wall medians increased 40.0% for the small fixture and 13.7% for the large fixture.

Scanner total CPU moved -13.0% and +0.2% respectively. Its large clean wall median increased 3.1%, with overlapping ranges.

This fallback variation reinforces the limit on wall-time attribution. It does not erase the eligible cases' recorded latency, CPU, or RSS costs.

The investigation found identical plan structure and join input counts. The probe-free follow-up did not reproduce the original small-Lance latency increase at the same magnitude.
Replay storage avoidance is established. These workloads show no uniform retry improvement in latency, CPU, or process RSS.

## Limits and raw evidence

RSS is the process high-water mark at merge completion, including imports and setup. It is not isolated replay memory.
The probe records completed spill-file size. `/proc/self/io` includes target writes and logging, and kernel-accounted writes can include cancelled writes.
Replay creates extra probe log writes. Very small elapsed-time differences can include this observation overhead and cannot establish pure replay savings.
Logical I/O, kernel I/O counters, all samples, and paired elapsed ratios remain in the JSON evidence. They do not prove physical device traffic.
These results cover local warm-cache workloads. They do not establish cloud, remote-storage, cold-cache, or update-heavy performance.

- Baseline extension: `cdfc0093f978a131a608fec65ac15f1526655832a3b571ca7b01e4ba1a53c6b6`.
- Candidate extension: `852dee3bca568063563fc9b66d2f13904b56cc796116fcdd27e5cefe71fa4114`.
- Fixture summaries: `benchmark-fixture-small-summary.json` and `benchmark-fixture-summary.json`.
- All comparisons: `performance-comparisons.json`.
- Per-process output: `raw/`. Replay events: `probes/`. Plan evidence: `plans/`.
- Detector controls: `controls/final/summary.json`. Reproduction commands: `README.md`.
