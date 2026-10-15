# IVF memory and spill: ChatGPT review package

This branch contains the candidate implementation and its review evidence for Lance #7305 and #7308.
Start here when reviewing `easyrev/lance:codex/ivf-build-memory-spill`.

| Revision | SHA |
| --- | --- |
| Upstream base | `08ea2c11674daf4791a00388b0bbe4bd9b339121` |
| Spill ownership fix | `dd95988d41ee9f92e47268c70327411ca4355c75` |
| Code candidate | `09d2c8a0deff51d59b77a83f68d54fed2c277710` |

Later commits that only change this directory package the reports. The code candidate SHA remains the review target.
These reports support review; they do not record upstream acceptance or complete closure of both issues.

## Reading order

1. [Delivery report](reports/delivery-report.md): behavior, scope, and remaining limitations.
2. [Design and maintainer evidence](reports/design-report.md): workload, policy decisions, and upstream links.
3. [Baseline comparison and code map](reports/baseline-comparison.md): implementation boundaries and files to inspect.
4. [Validation report](reports/validation-report.md): test results, reproduction commands, and evidence provenance.
5. [Resource diagnostic report](reports/resource-report.md): six measured cases and limits on performance conclusions.
6. [Independent review history](reports/independent-review-history.md): earlier findings and their disposition.
7. [Package audit](reports/package-audit.md): independent verification of this publication's claims and evidence.
8. [PR description draft](reports/review-description.md): a proposed upstream summary, not a submitted PR.

## Reviewer request

Review the diff from the upstream base to the code candidate. Report actionable correctness, resource-lifetime, and compatibility defects with file references.
Distinguish defects from the explicitly documented scope limits. Check the following areas first:

- Reservation lifetimes across flush, cancellation, CPU work, completed results, and optional offset eviction.
- Minimum working-set estimates for PQ conversion, fragment reuse, multivectors, and split/join operations.
- Session spill ownership, quota release, asynchronous shutdown, and reader lifetime.
- The default path and unsupported resource configurations.
- Whether the evidence supports each claim about memory, correctness, and performance.

Do not infer an RSS cap, arbitrary oversized-partition completion, optimized speedup, or maintainer approval from these reports.
The original test logs do not contain source hashes. See the validation report before attributing a run to a specific commit.

## Evidence and integrity

[Evidence index](evidence/README.md) describes every preserved implementation artifact.
Original files are copied without edits. Current reports explain which results supersede earlier ones.
[Publication manifest](publication-manifest.json) records SHA-256 hashes, source revisions, and candidate source-file hashes.
It excludes itself to avoid a self-referential checksum.

From the repository root, verify the bundle with:

```sh
python3 review/issue-7305-7308/verify_bundle.py
git diff 09d2c8a0deff51d59b77a83f68d54fed2c277710 HEAD -- . ':(exclude)review/issue-7305-7308'
```

The second command should show no implementation changes for this report publication.
The manifest verifies the packaged bytes; it cannot retrospectively prove which source tree produced an older log.
