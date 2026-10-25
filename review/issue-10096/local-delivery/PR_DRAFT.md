fix(index): retain valid staged coverage through v0 compaction

Publishing a staged segment after v0 deferred compaction discarded valid coverage and forced flat scans.
This affects publication from a newer dataset snapshot.

Retain original fragment provenance only when complete rewrite destinations remain fresh.
Keep `dataset_version` unchanged and compare normalized live coverage for replacement checks.
Reject packed-parent replacement races that affect an indexed child.
FM and JSON wrappers keep their existing scan fallback.
No format or public API changes.

Validation: 45 focused tests, 1591 broader index tests, and 146 conflict-resolver tests pass.
Workspace Clippy and formatting pass. The broader run includes the focused tests.

On 4M rows, five alternating rounds restore coverage from 0/8 to 8/8 fragments.
Every query scans one row instead of 4M rows.
With warm OS pages, median query time changes from 5.888 to 0.801 ms with fresh Lance sessions.
Reused sessions change from 5.616 to 0.519 ms.
Each cache mode contains 100 timed queries per variant.
These results exclude dataset opening and index publication.

Addresses #10096. JSON wrappers and already-mapped saved metadata remain outside the new retention path.
