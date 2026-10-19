# Import record

## Publication and source identity

The branch is `review/9505-merge-source-hypotheses`. This is a review-only study with no pure PR branch.
The repository source remains at baseline `0a0d327082988018a25f56147d3b6d02f6c79ecc`. No experimental driver becomes the repository default.
Source-snapshot commit `0a774f3929de1d7f6a23c971cb28b69f78f59969` preserves seven complete source files, four patches, and the reconstruction supplement.
The next commit preserves reports, original records, harness scripts, reference sources, and publication checks.
Original files retain their bytes. The import does not rebase, correct, or format the experimental source.

The experiment used a #10077 port plus private test drivers. The compiled source is `study/snapshot/`.
Seed files under `study/scripts/` precede rustfmt and need not match the compiled bytes.
The frozen `implementation.patch` omits one inherited untracked integration test.
`full-reconstruction.patch` includes it. [reconstruction-supplement.json](study/reconstruction-supplement.json) explains the difference and provides both patch hashes.
The lib executable did not compile that integration target.

## Checks performed for publication

The original ZIP SHA256 is `00bf9080c4a80f54bc22b616b6aa8504db14b63f5dbbc94360ba04a284cde57a`.
Every original archive file matches the ECS copy, including the unchanged 951-entry `study/SHA256SUMS`.
[ecs-verification.json](import/ecs-verification.json) records those 952 hashes and the actual binary identity.
ECS checks matched all 1196 source/configuration hashes and the frozen executable.

Local reconstruction used a disposable Git index and the complete patch on the clean baseline.
All 1196 reconstructed source hashes matched the freeze. All seven source snapshots matched the reconstructed Git blobs.
[source-verification.json](import/source-verification.json) records the result. The reconstructed tree ID is not a separately published candidate ref.

Local checks matched each result with its spec, metrics, resource record, validation record, and freeze identity.
They retained 47 successes, four controlled errors, and two plan-only records.
The original report extractor reproduced all 53 records and six complete paired comparisons. Only its root path changed.
These checks read saved assertions and measurements. They do not repeat dataset validation or the original live fixture/output-file audit.

No benchmark, build, dataset oracle, or Rust/Python code lint ran for publication.
Credential-pattern checks found no tokens, private keys, or authenticated URLs.
Archival commits bypassed hooks once per command to preserve historical bytes. No persistent hook setting changed.

## Paths and review commands

ECS `/mnt/lance/hypotheses-9505-20261019/<path>` maps to `review/issue-9505/study/<path>`.
Original absolute ECS paths and relative report links remain unchanged.
The archive excludes generated fixtures, per-case datasets, IPC outputs, environments, caches, and compiled binaries.
Their generators, identities, manifests, recorded validation results, logs, resource samples, and failure evidence remain available.

Read-only extraction from the repository root:

```sh
node review/issue-9505/study/scripts/report.cjs review/issue-9505/study
```

Apply `study/full-reconstruction.patch` to a separate checkout at the common baseline to inspect the complete experimental source.
Follow the repository environment workflow before any build or test. Source reconstruction does not establish a new successful build.
Keep stage probes separate from complete merges and preserve each comparison's input, cache, pool, and backing contracts.
Any new measurement requires a new result root and freeze.
The original audit and reconstruction scripts contain historical absolute paths and can write derived files. Inspect them before use.

The outer `SHA256SUMS` covers every packaged regular file except itself, including the unchanged inner checksum list.
Run `python3 review/issue-9505/import/verify-archive.py` to check it.
