# Packed-parent CreateIndex conflict: review notes

## Branches and commits

| Role | Ref | Commit |
| --- | --- | --- |
| Pure PR candidate | `fix/10096-packed-parent-index-conflict` | `86b4d717d20fbae583456523ee1dd4a8c3b6ac9a` |
| Review | `review/10096-packed-parent-index-conflict` | This branch tip |
| Upstream baseline | `lance-format/lance` `main` at investigation time | `168cab8e91dc1824d87050e02872fc9cecc5e573` |
| Upstream PR | None opened | — |

Sibling work: `fix/10096-staged-v0-coverage` and `review/10096-staged-v0-coverage` address the issue's staged coverage loss. This branch addresses a separate correctness bug found during that investigation. The issue number identifies the investigation; it does not imply that this fix resolves the coverage-loss issue.

## What to review

Check whether a CreateIndex on packed child `s.x` must conflict when a concurrent DataReplacement rewrites parent `s`. Check both direct `create_index` and staged-segment publication. Confirm that a `merge_insert` with `RewriteColumns` still commits with correct query results.

## Design and scope

The DataReplacement operation records the physical parent field. The new index records the child field. Before this fix, the conflict resolver compared only exact field IDs and allowed the stale index to commit. The fix uses `field_affects_index` with the read schema to detect the parent-child dependency. It applies only the `conflict_resolver.rs` hunk from `8ab094775ea0ef675abd96436bd122873ad194e2`. It does not include that commit's `index.rs` changes.

The three tests live in `rust/lance/src/dataset/optimize/tests/concurrent_reindex.rs`. That file already had the commit-race hook and fresh-session helpers. The added helpers create the packed dataset, perform each concurrent write, and count query rows.

## Results by revision

The counts below use the order `s.x = 333 / s.x = 3`. Each test scans the same data with the scalar index enabled and disabled.

| Tested commit | Test | Result | Indexed rows | Scanned rows | Raw log |
| --- | --- | --- | --- | --- | --- |
| `168cab8e91dc1824d87050e02872fc9cecc5e573` plus test changes only | Direct CreateIndex and DataReplacement | Failed as expected: stale index committed | `0 / 1` | `1 / 0` | `results/main-create-index.log` |
| Same baseline and test changes | Staged segment and DataReplacement | Failed as expected: stale index committed | `0 / 1` | `1 / 0` | `results/main-staged.log` |
| Same baseline and test changes | RewriteColumns control | Passed | `1 / 0` | `1 / 0` | `results/main-rewrite-columns.log` |
| `86b4d717d20fbae583456523ee1dd4a8c3b6ac9a` | All three regression tests | Passed: 3 tests | The two replacement cases returned retryable conflicts; the control found `1 / 0` | `1 / 0` | `results/final-regressions.log` |
| Same pure commit | Conflict resolver suite | 146 passed | — | — | `results/conflict-resolver.log` |
| Same pure commit | `index::` suite | 1,590 passed, 1 ignored | — | — | `results/index-tests.log` |
| Same pure commit | `cargo clippy -p lance --tests -- -D warnings` | Passed | — | — | `results/clippy.log` |

The baseline logs record the same behavioral assertions before their final naming and lint cleanup. The final regression log tests the pure commit exactly. `cargo fmt --all` passed before the pure commit.

## How to reproduce

On the pure branch, run:

```sh
cargo test --locked -p lance --lib --no-default-features --features tokio/test-util dataset::optimize::tests::concurrent_reindex::packed_parent_
cargo test --locked -p lance --lib --no-default-features --features tokio/test-util io::commit::conflict_resolver::tests
cargo test --locked -p lance --lib --no-default-features --features tokio/test-util index::
cargo fmt --all
cargo clippy -p lance --tests -- -D warnings
```

The runs used one local Mac (`Darwin arm64`) with Rust and Cargo 1.98.1. They used the existing local build cache. They did not use ECS.

## Files

`results/SHA256SUMS` records hashes for every shared log in `results/`. The logs retain compiler output and test summaries. The local checkout path was replaced with `<repo>` before publication. The original logs remain on the local Mac.
