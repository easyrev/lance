# Validation report

Review candidate: `09d2c8a0deff51d59b77a83f68d54fed2c277710`.
The evidence below was collected during implementation before the final code commit.
Logs were preserved without edits. They do not embed a source SHA or build fingerprint.
The task history identifies the final runs after the last input-batching change, but the logs alone cannot prove that revision association.

## Retained results

| Check | Result | Raw evidence | Stage |
| --- | --- | --- | --- |
| Full builder module | 29 passed | [final-resource-tests.log](../evidence/final-resource-tests.log) | Final affected-test run |
| Partition scheduler | 19 passed | [final-resource-tests.log](../evidence/final-resource-tests.log) | Final affected-test run |
| Build/optimize with Session spill | 2 passed: Flat/Greedy and PQ/FairSpill | [final-resource-tests.log](../evidence/final-resource-tests.log) | Final affected-test run |
| Split/join with fragment reuse | 2 passed | [final-resource-tests.log](../evidence/final-resource-tests.log) | Final affected-test run |
| Resource failure does not commit an index | 2 passed: disk cap and pool limit | [final-resource-tests.log](../evidence/final-resource-tests.log) | Final affected-test run |
| Default legacy-shuffler behavior | 1 passed | [final-resource-tests.log](../evidence/final-resource-tests.log) | Final affected-test run |
| Full shuffler module | 56 passed | [final-shuffler-tests.log](../evidence/final-shuffler-tests.log) | Final affected-test run |
| Wide input at 4 MiB | 2 passed: fixed vector and multivector | [wide-input-tests.log](../evidence/wide-input-tests.log) | Final input-batching change |
| Storage source ownership | 2 passed | [storage-tests.log](../evidence/storage-tests.log) | Earlier implementation run |
| Default index regressions | PQ 6; SQ 4; RQ 16; HNSW PQ 8; HNSW SQ 4; split/join 1; NULL 10; HNSW empty 1; optimize empty 1 | [default-regressions.log](../evidence/default-regressions.log) | Earlier implementation run |
| Full workspace Clippy | Completed successfully | [clippy-final.log](../evidence/clippy-final.log) | After final input-batching change |
| Shuffle diagnostic | Six cases passed exact row/vector checks | [resource-diagnostic.jsonl](../evidence/resource-diagnostic.jsonl) | Earlier implementation run; debug build |

The default-regression log also contains a zero-test filter. It provides no coverage.
Its older single-case resource test is superseded by the two-case final run and is not additional coverage.
Earlier builder, input-batching, and Clippy logs remain in the evidence directory for traceability.
Do not add their counts to the final runs or interpret them as additional independent cases.

## Results reported without a retained raw log

The implementation task recorded 19 passing `lance-io` spill tests and four passing `lance-file` metadata-spill tests.
It also recorded a successful `cargo fmt --all` run.
Their raw outputs were not saved in the evidence directory. These results therefore have weaker auditability than the linked logs.
No whole-workspace test run, sanitizer run, production-scale benchmark, or optimized baseline comparison is claimed.

## Reproduction

Follow the repository's [Rust environment instructions](../../../rust/AGENTS.md) before running Cargo.
These are reproduction commands derived from the recorded test filters, not a reconstruction of every original shell invocation.
Run the legacy-switch filter separately because it changes process-wide environment state.

```sh
cargo test --locked -p lance --lib index::vector::builder::tests
cargo test --locked -p lance --lib index::vector::bounded_partition_stream::tests
cargo test --locked -p lance --lib test_ivf_build_and_optimize_use_session_spill_store
cargo test --locked -p lance --lib test_ivf_budgeted_partition_adjustment_with_fragment_reuse
cargo test --locked -p lance --lib test_ivf_resource_failure_does_not_commit_index
cargo test --locked -p lance --lib test_ivf_legacy_shuffler_preserves_default_resource_behavior
cargo test --locked -p lance --lib vector_append_sizes_wide_input_batches_for_memory_pool
cargo test --locked -p lance-index --lib vector::v3::shuffler::tests
cargo test --locked -p lance-io --lib spill::tests
cargo fmt --all
cargo clippy --all --tests --benches -- -D warnings
```

The captured Clippy log contains build-script notices that optional fp16/bf16 kernels are disabled.
The earlier storage-test build contains dead-code warnings in the throttle module. The final full-workspace Clippy run still completed successfully.

## Publication checks

This publication changes only the review directory. It does not rerun source tests or claim a new execution of the existing results.
The bundle verifier checks file hashes, Markdown file targets, diagnostic invariants, and source-file hashes against the candidate.
The independent [package audit](package-audit.md) checks the evidence and report claims separately.
