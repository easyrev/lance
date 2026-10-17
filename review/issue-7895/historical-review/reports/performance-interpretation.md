> Historical report. Status statements describe the stage when this report was written. See the [review index](../README.md) for the published branch context. Only links were adapted below. The [original report](../evidence/performance-interpretation.md) remains byte-identical.

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
