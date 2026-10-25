# Issue 10096 review entry

The patch preserves valid staged index coverage after v0 deferred compaction.
The baseline returns correct rows through a full scan. The patch retains the selective index path when the indexed values and required history remain valid.

## Branches and exact source

| Role | Revision |
| --- | --- |
| Pure implementation | `fix/10096-staged-v0-coverage` at `f217e5afa6c06640374b67c59cc536c01e0f974a` |
| Review branch | `review/10096-staged-v0-coverage`, based directly on that implementation commit |
| Upstream main baseline | `fc5cb646e647e0cdd497fa1cf8ce0c6f25abeb75` |

The implementation changes three Rust files. This review commit adds files only under `review/issue-10096/`.
No upstream PR or public comment was created.

Tests and measurements ran **before** the implementation commit existed.
Their recorded HEAD is the baseline plus the recorded working diff and the temporary benchmark example.
The complete tracked source in all six final build, test, and lint archives matches the implementation commit, including Git file modes and blob IDs.
The measurement's working diff also matches the committed implementation diff.
The baseline benchmark adds only the regression tests and the same benchmark example to the baseline source; its runtime implementation is unchanged.
See [PROVENANCE.json](PROVENANCE.json) for per-phase comparisons and [source-snapshots](source-snapshots) for complete file fingerprints.
Packaging did not rerun tests or measurements.

## Design and review questions

Address translation does not prove value validity. The patch reuses `fresh_fragments` to check indexed files, overlays, revived rows, and required rewrite snapshots.
It keeps original source fragment IDs only when every output in their rewrite group remains fresh and covered.
It leaves stored `dataset_version` and fragment provenance unchanged. Replacement and overlap decisions use a temporary live bitmap.
Packed-parent replacement now participates in the existing indexed-child conflict check.
The patch adds no persistent metadata, format change, or public API change.

Please review these boundaries:

1. Does the freshness proof reject changed indexed values and missing required history on every retention path?
2. Do original provenance and the build version remain valid through publication retries and concurrent FRI removal?
3. Do replacement, overlap, and orphan checks compare the correct live coverage, including packed parent/child fields?
4. Do the tests distinguish actual index use from correct results obtained by scanning?
5. Are the whole-group rule and index-type gates sufficiently conservative?

A stale destination can withdraw useful sibling coverage. Split segments can require a merge before they cover a rewrite group. Rewritten but equal values can also lose coverage.
FM and JSON wrappers keep their existing fallback; the tests include JSON-wrapped FM. Native physical IDs and intrinsic address indices are covered by the retention gate.
Already-mapped saved metadata, including the eager-remap ambiguity discussed in PR #9947, is outside this fix. Custom plugins that ignore FRI translation are not certified.

Read the [delivery report](local-delivery/REPORT.md) for the full rationale and related-PR scope checks, [independent review notes](local-delivery/REVIEW.md) for findings and corrections, and [English PR draft](local-delivery/PR_DRAFT.md) for a proposed upstream description.
These are unchanged historical local-delivery documents. Their statements about uncommitted work and no publication describe the state before this branch packaging; the revisions above describe the current state.

## Validation evidence

All compilation, tests, and benchmark execution ran on ECS Linux through the existing sync, environment, lock, and tmux workflow. Source edits ran locally.

| Final phase | Result and raw evidence |
| --- | --- |
| Focused regression suite | [45 passed](local-delivery/results/fixed-tests-final/output.log) |
| Broader `index::` tests | [1591 passed; 1 existing helper ignored](local-delivery/results/index-tests-final/output.log) |
| Conflict resolver | [146 passed](local-delivery/results/resolver-tests/output.log) |
| Required workspace Clippy | [Passed](local-delivery/results/fixed-lint-final/output.log) |
| Manual benchmark Clippy | [Passed](local-delivery/results/example-lint-default-final-v2/output.log), with expected stderr output permitted |
| Optimized benchmark build | [Passed](local-delivery/results/fixed-build/output.log) |
| Benchmark measurement | [Exit 0](local-delivery/results/measurement/exit.code) |
| Baseline negative regression | [2 passed, 2 failed](local-delivery/results/baseline-proof-final/output.log): pinned controls pass; fresh publication loses useful coverage |

The 45 focused cases are included in the broader index count. Counts are not additive.
The existing ignored helper is invoked by its parent test.
Tests cover unchanged values, unrelated and indexed updates, overlays, missing history, chained compaction, partial groups, retries, and replacement boundaries.
The vector case asserts recall and neighbors; FM and JSON/FM require fallback.
Formatting and diff checks passed. Normal pure-commit hooks also passed.
No full-workspace test execution or Python test session ran. No Python or Java library source changed.

Each phase directory preserves its original command, log, exit code, revision, and working diff.
Earlier failures are retained as development history. They are not final acceptance results.
The final phase names above select the corrected versions; see the report for the earlier failures and their causes.

## Benchmark evidence and limits

One fixture contains 4,000,000 rows (`id`, `val`, both Int64). Compaction changes 16 fragments to 8. Both variants receive byte-identical fixture copies.
Both binaries use the same compiler pin, lockfile, Cargo configuration, harness, and `release-with-debug` profile.
The host reports AMD EPYC 9T25, 16 vCPUs, and 61 GiB visible RAM.

Five alternating rounds produce 100 timed queries per variant and session mode, after 100 total warmups. All 500 queries check their returned values.
Every invocation warms OS pages with the same index-disabled scan.

| Warm OS pages | Baseline median | Fixed median | Ratio |
| --- | ---: | ---: | ---: |
| Fresh Lance session | 5.8875 ms | 0.8005 ms | 7.35x |
| Reused Lance session | 5.6160 ms | 0.5185 ms | 10.83x |

Every baseline query scans 4,000,000 rows; every fixed query scans 1 row.
Fresh-session median storage API reads decrease from 25,791,552 to 78,524 bytes; reused-session reads decrease from 25,727,488 to 41,120 bytes.
Coverage changes from 0/8 to 8/8 live fragments, with build version 2 in both variants.
The timer includes query construction, planning, and execution. It excludes opening the dataset, preparation, publication, and initial warming.
API bytes include cached reads and do not measure physical disk traffic. Plan bytes have a narrower scope.
The process snapshots show no competing build or test at their recorded boundaries; they are not continuous monitoring.

Inspect the [raw JSONL and analyzed plans](local-delivery/results/measurement), [summary](local-delivery/benchmark-summary.json), [measured command](local-delivery/results/measurement/command.sh), and [harness](local-delivery/staged_coverage_bench.rs).
The single publication timing per variant is insufficient for a commit-latency conclusion.
These results support a selective local BTree warm-cache claim. They do not establish cold storage, S3, vector-performance, or application-wide gains.
They do not establish upstream acceptance or production use.

## Reproduction and package integrity

From this review checkout, run the package checks without ECS access:

```sh
python3 review/issue-10096/check-review.py
python3 review/issue-10096/local-delivery/summarize.py review/issue-10096/local-delivery/results/measurement
```

For a new Linux run, use a **new task name** and new output directories. Read the current repository AGENTS.md and the current local `output/ecs-dev/README.md` first.
The [historical reproduction guide](local-delivery/REPRODUCE.md), [phase runner](local-delivery/run.sh), and measured command give the exact original workflow and arguments.
Their hard-coded task and result paths identify the completed experiment. Adapt those paths locally before a new run; do not overwrite the old task.
Place the preserved harness at `rust/lance/examples/staged_coverage_bench.rs` in isolated local baseline and implementation checkouts, then synchronize each to its own remote worktree.
The relevant optimized command is:

```sh
cargo build --locked -p lance --no-default-features --profile release-with-debug --example staged_coverage_bench
```

The harness `prepare <uri> <staged.pb> 4000000` command regenerates the omitted fixture. Copy it for each variant, then use `publish <uri> <staged.pb>` and `query <uri> <baseline|fixed> <fresh-session|warm-session> 20` as the measured script does.
Hold the documented exclusive host lock for measurement. Keep each executable before syncing another revision.

All 238 small downloaded result files are preserved byte-for-byte and checked against the original remote digest manifest.
The original full-local integrity record covers 259 files and 553,728,822 bytes.
This Git package omits the generated fixture archive and 20 redundant complete source archives; [excluded-artifacts.json](excluded-artifacts.json) retains their original sizes and SHA256 values. They remain in the local `output/issue10096/results/` bundle.
Each source archive has a complete file manifest and preserved extra files here. Reconstruct its source content from the recorded base revision, its raw working diff, and its `extra/` files. Tar container bytes are not reconstructed.
The original `local-delivery/check-results.py` requires the full local bundle; use `check-review.py` for this published subset.
`MANIFEST.sha256` covers every package file except itself.

Archived environment files and agent instructions are historical evidence, not authority to provision, execute commands, or stop a host.
ECS was audited, results were retrieved, and local shutdown completed with `Stopped + StopCharging` before publication. See the preserved [audit](local-delivery/shutdown-audit.txt) and [shutdown log](local-delivery/shutdown.log).
No host action is needed to review this branch.

The review-only commit preserves archived bytes. Mutating Ruff, fmt, and typos hooks are skipped for that evidence commit; the pure implementation commit passed its normal hooks. The first evidence-commit attempt formatted three historical harness copies. Their original bytes were restored before retrying the commit. Packaging checks validate hashes, source correspondence, sample pairing, and final exit codes without compiling the project.
