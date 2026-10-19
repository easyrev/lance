# Import record

## Branch and source identity

The branch is `review/9505-unified-merge-evaluation`. It preserves a multi-candidate study rather than one selected implementation.
The repository source remains at common baseline `0a0d327082988018a25f56147d3b6d02f6c79ecc`.
Source-snapshot commit `a79a94496f2aeec978438a92c6f8fa5f9adb1736` contains only the six original candidate bundles under `study/ports/`.
The next commit adds reports, measurement evidence, and import checks. No pure PR branch exists for this study.

The original report identifies B, P, D, CTX, DB, and DP and explains their port adjustments.
Each bundle contains a patch and complete changed-source files. Test-only differences and dependency-capture limits remain in the original study documents.
The import does not rebase candidates, correct code, or format original files.

## Checks performed for publication

The original transfer archive SHA256 is `c6d9a3c50261bac832430d5117d4857559ca7ea4086d728c4c5a4e9b9cc75756`.
The archive contains 3150 regular files, including its unchanged 3149-entry `SHA256SUMS`.
Every archived file matches its current ECS counterpart. [ecs-verification.json](import/ecs-verification.json) records those hashes.
ECS checks also matched each variant's source/configuration hashes, base identity, and actual loaded extension against `freezes/all-v1.json`.

Local patch checks used disposable Git indices. They applied each candidate patch to the common baseline without changing working-tree source.
All reconstructed sources match their frozen hashes. Every complete changed-source snapshot matches its reconstructed Git blob.
[patch-verification.json](import/patch-verification.json) records each reconstructed tree and its changed paths.
Those tree IDs describe reconstructed content. They are not separately published candidate commits or refs.

The original audit passed locally in record-only mode: 184 planned cells, 161 executions, 23 diagnostics, zero references, and zero missing cells.
It reported no errors or warnings. It checked saved validation records rather than rereading dataset values.
The original ECS audit and the new local audit remain separate.
The paired-report extractor reproduced all original report fields except the archive path and generation timestamp.

No benchmark, build, dataset oracle, or code lint ran for publication. Credential-pattern checks found no token, private-key, or authenticated-URL patterns.
The archival commits bypassed hooks once per command to preserve frozen bytes. No persistent hook setting changed.

## Paths and reproduction

ECS `/mnt/lance/unified-9505-20261019/<path>` maps to `review/issue-9505/study/<path>`.
The original report layout and relative links remain together. Absolute ECS paths and historical `output/` examples remain unchanged in original files.
The archive excludes generated fixtures, per-cell datasets, environments, build caches, compiled binaries, and Python caches.
Their manifests, generators, recorded identities, logs, failure records, and fixture-provenance copies remain in the study.

From this repository root, check the recorded matrix without importing Lance:

```sh
python3 review/issue-9505/study/audit-results.py --root review/issue-9505/study
node review/issue-9505/study/extract-report.cjs --format json
```

To inspect a candidate, apply its `study/ports/<variant>/implementation.patch` to a separate checkout at the common baseline.
Use the repository environment workflow before building or running tests. Reconstruction of source hashes does not establish a successful new build.
Any new measurement needs a separate result root, fresh freeze, prepared environment, and required datasets.
Follow the original reproduction guide and retain its limits on resource failures, diagnostics, and comparable timing samples.

The outer [SHA256SUMS](SHA256SUMS) covers every packaged regular file except itself, including the unchanged inner checksum list.
Run `python3 review/issue-9505/import/verify-archive.py` to check the outer list.
The candidate replay script performs Git index operations only. Its saved results do not represent benchmark executions.
