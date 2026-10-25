# Review of staged segment coverage

An independent agent reviewed the production diff and the regression design.
The review examined index validity, identifier domains, version semantics, replacement decisions, and publication retries.
The reviewer did not edit source or run builds.

The review found these issues during development:

1. FM accepts an FRI argument but does not translate its stored addresses. The patch excludes FM from the new retention path.
2. Persisting mapped coverage before publication can hide lost translation history on retry. The patch retains original fragment provenance instead.
3. Replacement checks compare incoming coverage with existing normalized coverage. The patch normalizes a temporary copy for those checks.
4. A packed parent replacement can change an indexed child. The existing v0 conflict check now recognizes that dependency and rejects publication.
5. Native row IDs are physical addresses when stable IDs are disabled. The retention condition now includes that domain.
6. The packed replacement test compared incompatible collection types. The test now compares slices.
7. A subset assertion allowed empty provenance to pass. The retry tests now assert exact stored bitmaps.
8. A plan check recognized only legacy scans. The regression now checks execution counters and compares actual rows with an index-disabled query.
9. JSON-wrapped FM bypassed the direct FM check. JSON wrappers now retain their existing scan fallback.

The final source review reported no remaining P1 finding.
Runtime results and benchmark conclusions belong to the delivery report and raw result files.

The patch keeps `dataset_version` unchanged.
It checks indexed files, overlays, and restored rows through the required rewrite snapshots.
It retains retired provenance only when every destination of its rewrite group remains covered and fresh.
Missing required snapshots or mappings leave the affected rows on the scan path.
Publication retries retain the original bitmap, so removed FRI mappings cannot create a false live claim.

The reverse walk deliberately requires complete destination coverage.
One stale destination can therefore withdraw coverage from other destinations in the same group.
This conservative behavior preserves query correctness.
Per-segment checks also leave split rewrite groups on the scan path unless the caller merges their segments first.

The patch does not solve arbitrary saved metadata whose bitmap already names post-build fragments.
That case includes the eager-remap ambiguity discussed in PR #9947.
The patch adds no persistent metadata and changes no file format.
The regression covers built-in BTree, IVF-flat, FM, and JSON-wrapped FM behavior.
JSON wrappers do not gain coverage from this patch.
It does not certify custom plugins that ignore FRI translation.
