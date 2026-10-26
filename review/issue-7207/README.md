# Issue 7207: reclaim index directories from lost commits

## Branches and commits

| Role | Ref | Commit |
| --- | --- | --- |
| Pure PR | `fix/7207-reclaim-lost-commit-indices` | `a108f280a22e1654317f75ce57e18ae8f5cd382e` |
| Review | `review/7207-reclaim-lost-commit-indices` | `bffadf8cba25c21024428366f79695c291fc05bc` before this documentation bundle |
| Upstream baseline | `upstream/main` | `88d8b1cc7dadf1e27eba67b853d2113ac2c6c318` |
| Upstream PR | Not opened; GitHub review comes first | — |

The review branch contains the pure branch plus files under
`review/issue-7207/` only. The pure branch history is `624151d1d` (tests and
test hooks), `4cdeeb48e` (cleanup implementation), `794da1438` (bounded commit
future for the Clippy large-future check), and `a108f280a22e` (custom remapper
ownership correction).

## What to review

Review whether cleanup is limited to index UUIDs owned by the transaction and
is reached only after the current attempt is proven not to have landed. The
highest-risk cases are a landed manifest that still returns an error, a rebase
that replaces a fragment-reuse UUID, and caller-owned operations that can replay
the same transaction. In particular, external `IndexRemapper` implementations
may reuse a `new_id` across retries and must not trigger directory cleanup.

## Design and scope

The cleanup is called beside `cleanup_transaction_file` on verified `Foreign`
or `Absent` outcomes, on terminal verified retry exhaustion and timeout, and at
the reporter's terminal pre-write `check_txn` conflict. It is not called between
internal retries and it does not run for `Ours` or `Unknown`.

The transaction-owned scope is:

- Default `compact_files()` with the built-in remapper: Rewrite directories from
  `rewritten_indices[].new_id`, excluding `new_id == old_id`.
- `Rewrite.frag_reuse_index.uuid`, including UUIDs replaced by later rebase
  attempts and tagged assemblies returned by `finish_rewrite`.
- A consumed `CreateIndexBuilder::execute` call that generated its own UUID.

The public `commit_compaction()` entry and `compact_files()` calls with a
caller-supplied remapper preserve all `rewritten_indices[].new_id` directories,
because the remapper trait does not prove per-call ownership. Their internal FRI
UUIDs are still reclaimed.

Generic `Dataset::commit`, Python caller-built transactions, distributed or
uncommitted index builds, `commit_existing_index_segments`, explicit
`index_uuid(...)`, and caller-supplied Rewrite operations remain replay-safe
and are excluded.

Cleanup resolves and reads the latest manifest and its index list inside the
helper. If either read fails, all deletion is skipped and logged. Referenced
UUIDs are subtracted before recursive directory deletion. Delete failures are
logged and never replace the original commit error.

Data-file cleanup is out of scope. A replayed `RewriteResult` can carry data
paths from an earlier ambiguous attempt, as documented by #7722. The FTS
half-written active-index failure reported by rafidowla has a different
correctness failure and is also out of scope.

See [DESIGN.md](DESIGN.md) for the line-level research answers and ownership
matrix.

## Reproduction

Generate the red evidence from the test-only pure commit:

```bash
git switch 624151d1d
export CARGO_TARGET_DIR=/private/tmp/lance-target-7207
cargo test -p lance --lib test_rewrite_loss_reclaims_remapped_index_directory
cargo test -p lance --lib test_rewrite_loss_keeps_custom_remapper_index_for_replay
cargo test -p lance --lib test_deferred_rewrite_loss_reclaims_spilled_fri_directory
cargo test -p lance --lib test_rebased_fri_loss_reclaims_original_and_replacement_directories
cargo test -p lance --lib test_create_index_loss_reclaims_new_index_directory
cargo test -p lance --lib test_landed_index_commit_returning_error_keeps_directory
cargo test -p lance --lib test_rewrite_preempted_by_delete_reclaims_remapped_index_directory
```

Run the final checks from the pure commit:

```bash
git switch fix/7207-reclaim-lost-commit-indices
export CARGO_TARGET_DIR=/private/tmp/lance-target-7207
cargo test -p lance --lib dataset::tests
cargo test -p lance --lib dataset::optimize::tests
cargo test -p lance --lib dataset::write::commit::tests
cargo test -p lance --lib index::create::tests
cargo test -p lance --lib io::commit::tests
cargo test -p lance --lib utils::test::tests
cargo fmt --all --check
cargo clippy -p lance --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc -p lance --no-deps
```

The optional race script needs a built Python extension and a new local table
path on a data disk:

```bash
cd python
uv run make build
uv run python ../review/issue-7207/bench/measure_lost_indices.py \
  --uri /data/issue-7207-pure \
  --output /tmp/issue-7207-pure.json
```

Run the same command for each checkout. The script reports the exact git
commit, lost compaction commits, unreferenced `_indices/` directory names and
bytes, and wall time.

## Environment

- Requested benchmark host: `ecs.g9a.4xlarge`, 16 vCPU, 64 GiB RAM, ESSD disks.
- This evidence bundle's Rust tests and static checks ran on macOS 27.0.1
  arm64 with `rustc 1.98.1` and `cargo 1.98.1`.
- `sccache` was not installed. `CARGO_TARGET_DIR` was
  `/private/tmp/lance-target-7207`.

## Results by revision

| Date | Tested commit | Relation | Method | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| 2026-10-26 | `88d8b1cc7` | Upstream baseline | Seven required tests on test-only tree `624151d1d` | All seven failed because orphan UUID directories remained | [red.log](logs/red.log) |
| 2026-10-26 | `a108f280a` | Final pure commit | Nine targeted tests | 9 passed | [green.log](logs/green.log) |
| 2026-10-26 | `a108f280a` | Final pure commit | Changed-module Rust suites | 1532 passed, 0 failed, 1 ignored | [modules.log](logs/modules.log) |
| 2026-10-26 | `a108f280a` | Final pure commit | fmt, clippy, rustdoc | All passed | [static-checks.log](logs/static-checks.log) |
| 2026-10-26 | `a108f280a` plus temporary source mutation | Final pure commit with custom-remapper ownership guard removed | Ownership mutation | New replay test failed because the external directory was deleted; source restored | [mutation-07-custom-remapper-ownership.log](logs/mutation-07-custom-remapper-ownership.log) |
| 2026-10-26 | `794da1438` plus temporary source mutations | Earlier pure commit | Six mutations | Each mutation was caught by its named test; source restored | `mutation-01` through `mutation-06` |
| 2026-10-26 | `88d8b1cc7` and `a108f280a` | Baseline and final pure commit | Repeated optimize/delete race | Not measured | [RESULTS.md](results/RESULTS.md) |

The red log names `624151d1d` as the tree under test; its only difference from
the baseline in the relevant code is the new tests and failure-injection
plumbing. The final implementation is not present in that tree. The baseline log
retains the original test name `test_rewrite_loss_keeps_index_when_remap_reports_keep`;
that scenario became `test_rewrite_loss_keeps_custom_remapper_index_for_replay`
when the external-remapper ownership rule was added.

## Mutation coverage

| Removed part | Catching test | Log |
| --- | --- | --- |
| Initial transaction UUID collection | `test_rewrite_loss_reclaims_remapped_index_directory` | `mutation-01-no-id-collection.log` |
| Rebase UUID accumulation | `test_rebased_fri_loss_reclaims_original_and_replacement_directories` | `mutation-02-no-rebase-accumulation.log` |
| Latest-manifest subtraction | `test_lost_index_cleanup_keeps_latest_manifest_index` | `mutation-03-no-live-manifest-subtraction.log` |
| `new_id == old_id` filter | `test_collect_transaction_index_ids_skips_keep_remaps` | `mutation-04-no-keep-filter.log` |
| Reporter pre-write cleanup | `test_rewrite_preempted_by_delete_reclaims_remapped_index_directory` | `mutation-05-no-reporter-cleanup.log` |
| Verified-loss cleanup | `test_rewrite_loss_reclaims_remapped_index_directory` | `mutation-06-no-verified-loss-cleanup.log` |
| External remapper ownership | `test_rewrite_loss_keeps_custom_remapper_index_for_replay` | `mutation-07-custom-remapper-ownership.log` |

## Open risks and merge points

- Cleanup reads fail closed: a read failure leaves orphan directories rather
  than risking a live directory deletion.
- Non-commit rebase construction errors that already minted a fragment-reuse
  directory are not covered by this small change.
- Caller-owned operations remain excluded even when they write index
  directories, because the caller can replay the same UUID.
- Public `commit_compaction()` and custom `compact_files()` remappers also keep
  their remapped-index directories after verified loss. This trades a possible
  leak on those paths for replay safety; default `optimize()` still reclaims
  them.
- #10146 can conflict through its `conflict_resolver.rs` split. #10034 and
  #10159 can conflict in retry/outcome handling. The local #10096 PR1 and
  open Rewrite/FRI PRs can conflict near rebase assembly.
- End-to-end race measurement is absent; unit evidence is the required
  correctness evidence.

## Files

| Path | Purpose |
| --- | --- |
| `DESIGN.md` | Phase 1 gate answers with source paths, line numbers, and ownership/replay evidence |
| `PR.md` | Review-draft upstream PR description |
| `bench/measure_lost_indices.py` | Optional local IVF_PQ optimize/delete race measurement |
| `results/RESULTS.md` | Explicit `Not measured` result table |
| `logs/red.log` | Baseline failures for all seven required scenarios |
| `logs/green.log` | Nine passing targeted tests on the final pure commit |
| `logs/modules.log` | Passing changed-module suites |
| `logs/static-checks.log` | fmt, clippy, and rustdoc results |
| `logs/bench-pycompile.log` | Python syntax check for the measurement script |
| `logs/mutation-*.log` | Seven source-removal checks and their catching tests |
