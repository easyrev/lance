# Issue #7895 / PR #9617: review package

This branch contains the public PR implementation and two sets of review records.
The pure branch is `feat/7895-rescannable-sources`.
The review branch is `review/7895-rescannable-sources`.
The additional review commit changes only `review/issue-7895/`.

## Start here

1. Read the [ECS benchmark summary](benchmark-2026-10-17/results/summary.md).
2. Check its [environment and revisions](benchmark-2026-10-17/results/env.md).
3. Inspect the [raw results](benchmark-2026-10-17/results/raw.jsonl), [scripts](benchmark-2026-10-17/harness/), and [run evidence](benchmark-2026-10-17/results/runs/).
4. Read the [earlier implementation and review reports](historical-review/README.md) for API, correctness, and design context.

The benchmark [brief](benchmark-2026-10-17/pr9617-scaling-brief.md) records its questions and measurement contract.
The [historical benchmark README](benchmark-2026-10-17/README.md) describes the original ZIP contents.
The [manifest](manifest.json) identifies the sources and publication changes.

## Which code was tested

| Object | Revision |
| --- | --- |
| Public PR #9617 head and this review branch's code parent | `ff576648ac969f0379400748c987c29d986a288f` |
| Parent of the public PR implementation | `4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9` |
| Earlier local candidate used by the historical review | `26632629ca162cdbfd82dabad1d80e3e6c92b364` |
| ECS benchmark upstream baseline | `dc53d5d174af62c49ddd98d1024a64488c1e4404` |
| PR implementation rebased onto that baseline for the ECS benchmark | `e18df5f4708b42be99aa33ec9ac12de15401982f` |

The public PR and earlier local candidate have identical code trees and parents.
Their commit identities differ because their author and committer identities differ.
The consolidation commit uses the public PR head as its first parent.
It also retains the former review head as its second parent to preserve that history.

The ECS benchmark tested a rebase onto the newer baseline.
It did not test this review checkout directly.
The public PR patch and the [measured rebased patch](benchmark-2026-10-17/results/pr.patch) have the same stable patch ID:
`12bf58d204d22624576c3e68b2cbfa0917cd3e33`.
The baseline and retained patch are sufficient to reconstruct the measured source when the temporary rebased commit is unavailable.
This publication does not rebase or update PR #9617.

Review the implementation separately from these records:

```sh
git diff 4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9 \
  ff576648ac969f0379400748c987c29d986a288f
```

## Evidence boundaries

The ECS benchmark contains 288 measured runs, with 144 per revision.
Of these, 287 completed successfully and passed their recorded verification.
One upstream run failed with the expected restricted-TMP `ENOSPC` error.
The reports explain cold and warm cases, input sizes, retries, and diagnostic runs.
Do not combine the earlier review measurements with the ECS matrix as one sample population.

Both directories preserve their source files byte for byte, except for three excluded Python bytecode cache files from the ZIP.
No measured values, logs, reports, or benchmark scripts were edited during publication.
The previous review branch contained 978 historical files, all retained here.
Historical claims about publication status, branch names, local paths, and files remaining on ECS describe the original recording date.
They are not statements about the current repository or the availability of that server.

The original ZIP SHA-256 is:
`566fdd9c544c837ab6246fc66c742cbfa6c5ee839d637d8552910b776f39112d`.
Its original manifest includes the three excluded cache files.
Use the new publication manifest to verify this directory:

```sh
cd review/issue-7895
sha256sum -c ARTIFACTS.sha256
```

The earlier review's manifests and original compressed archive remain unchanged inside `historical-review/`.
The root `ARTIFACTS.sha256` covers every published file except itself.

## Reproduction on a new host

Read the recorded environment and the repository's language-specific guides first.
Rebuild the pinned sources and regenerate datasets with the retained scripts.
The raw dataset payloads, virtual environments, and Cargo build caches are not included.
Readable profiler reports are included, but raw perf and heaptrack recordings are not.

The ECS scripts retain `/mnt/lance/bench-9617` paths and references to host environment and proxy scripts.
Those host scripts and credentials are not part of this package.
Prepare the environment or adapt those references before execution.
The historical build script also expects `/mnt/lance/target` as a cache seed.
A new host must build its own cache before using that optimization, or omit the seed step.
Cold-cache and loop-device scenarios require appropriate host privileges.
Use dedicated generated benchmark datasets because preparation scripts can remove old dataset versions.

Reading these records does not require running the historical scripts.
Publication validation checks file integrity and an unchanged implementation tree.
It does not rerun the benchmark or extend its acceptance claims.

## Branch maintenance

Make implementation changes on the pure branch first.
Then bring those commits into this review branch and update the affected evidence.
Keep review materials out of the pure branch.
Preserve old measurements with their original revisions when new measurements are added.
The archived `historical-review` directory replaces the material from `codex/issue-7895-reviewed-candidate`.
