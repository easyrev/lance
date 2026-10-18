# Candidate C-r2 re-review

Date: 2026-10-18. Scope: current source diff and the C-r2 bench.py and semantic.py. The reviewer did not edit source, build, run Cargo, or run performance cases. The C-r1 review remains unchanged.

## Decision at initial re-review

The inspected corrections address the earlier source-validation and measurement-isolation defects. No new blocking wrong-result or resource-sharing defect was found by source inspection.

Formal measurement clearance remains pending. The current optimized regression build is incomplete. The native test also needs the in-flight cancellation coverage described below. This report must not be read as a test-pass record.

## Corrections accepted by source inspection

- merge_insert.rs:2521 validates source compatibility before reporting a missing join key. It checks all join keys before any preparation poll. This preserves SchemaMismatch precedence and closes the invalid-source Pending case.
- Preparation now parses conditions before polling. Its sizing projection includes ROW_CREATED_AT_VERSION_FIELD when carried lineage requires it.
- stats_guard.rs tests the actual optimizer.use_statistics_registry switch, a bytes-only counterfactual, and dual-Absent behavior through JoinSelection. It asserts the optimized build identity and CollectLeft versus Partitioned mode. The previous getter-only gap is closed.
- logical_plan.rs tests the small-target model below, exactly at, and above the threshold. It also checks that Complete source evidence selects source first. The join remains Auto for subsequent normal optimization.
- Full plan and formatted operator-metric output require LANCE_MERGE_DIAGNOSTICS. bench.py removes the inherited flag and enables it only for diagnostic invocations. Formal timings therefore omit that detailed C-only formatting.
- semantic.py asserts actual MergePayload presence and take-row counts. Its source-error case now crosses the row prefix threshold before raising an error. It checks that the attempt leaves the snapshot and contents unchanged.
- Source-error unit coverage checks the root DataFusion error variant and message. Source cancellation covers both initial Pending and Pending after a prefix.
- The projected-width resource test describes wide fields without allocating payloads. It checks P reduction to two and one, constant nominal pool size, constant prefix budget, and matching context P. This is valid policy coverage. Actual scanner P and the absence of an expanding RoundRobin remain execution diagnostics.
- execute_uncommitted explicitly disables retry spilling. This preserves its non-retry behavior while allowing bounded preparation.
- The source evidence revision now identifies C-r2. PartialOrd includes deferred_target_columns.

## Remaining blocking evidence

### Native cancellation must cover a task that is still Pending

Location: rust/lance/src/io/exec/filtered_read.rs:4127.

The current test drops partition zero after next() returns a completed batch. It proves reset and shared-state ownership release. It does not prove that cancellation drops an in-flight task, or that another worker can acquire work while the first worker waits. Its missing-file error may occur during fragment initialization rather than within a claimed batch task.

The parent received a deterministic test pattern. Construct a private FilteredReadStream with MultiplePartitions(2) and two synthetic MaterializedReadBatchesFut tasks. Both tasks remain Pending and own drop guards. Poll both partition next futures once. Assert that both tasks start, which proves the shared lock is released before the task await. Drop both pending futures and streams. Assert that both task guards drop. A second case can return an error from one task while its peer stays Pending.

This test needs no sleeps, task spawning, payload allocations, or external process kill. Run it after compilation and include its result in the freeze evidence.

### Required test and mechanism results remain pending

The reviewer saw historical C-r1 logs for the optimizer counterexample and threshold tests. Those logs also contain the rejected revision's two regression failures. They cannot establish C-r2 success.

Before formal measurements, attach the C-r2 merge regression result, native tests, payload test, corrected binary identity, and external Early/Late semantic result. Classify any remaining regression against the frozen baseline with evidence. Keep the earlier failures in their original result directory.

## Remaining claim limits

- payload_take_arrow_bytes measures returned Arrow memory. It does not measure physical Take I/O. The aggregate scan_take_bytes does not automatically include TakeBuilder storage reads.
- The new cancellation tests prove behavior at their tested boundary. They do not establish preemption of a synchronous Python producer or a wall-clock source-preparation deadline.
- The width-derived scan budget remains a soft estimate. The new P test does not establish a process-wide memory bound.
- bench.py selects the largest resident process inside the worker cgroup for RSS sampling. Cgroup metrics cover the full group. Do not describe the selected-process RSS as the sum of all process RSS.
- The small pool diagnostic validates its updated field for successful small input and unchanged contents for a failed operation. Verify its actual reservation consumer before treating failure as proof of pool enforcement.

## Non-blocking observations

The small-target rule and StatsGuard preserve normal optimizer processing. Native repartitioning still constructs fresh state and shares one task stream. MergePayload still serializes payload Takes after action assignment and uses physical addresses from the operation snapshot. These source properties remain consistent with the design.

Acceptance may be appended after the pending lifecycle test and C-r2 checks complete. Do not alter C-r1 evidence.

## Follow-up: native Pending boundary test

The reviewer inspected native_workers_release_pending_tasks at filtered_read.rs:4072 after the initial re-review. Its cancel_pending case polls two tasks through the real MultiplePartitions get_stream path. Both tasks start while the first remains Pending. This checks that workers release the shared stream lock before awaiting their task.

Both tasks own drop guards. Cancelling the pending next futures and streams must drop both guards. The worker_failure case returns an error from the second claimed task while the first remains Pending. It checks the propagated DataFusion error and subsequent cleanup.

This closes the source-level lifecycle coverage gap. No further source correction is requested. Compilation, the two test outcomes, and the final extension identity remain pending. No performance clearance is implied until those results are attached.

## Follow-up: reduced scanner partition test

The new native_merge_policy_preserves_reduced_partitions test checks scanner P, budgeted batch rows, I/O settings, native output P, and rejection of expansion to 16 outputs. It complements the context-policy test.

Initial inspection found a test-fixture defect at scanner.rs:9143: dataset.empty_projection() selects neither fields nor row identity. FilteredReadExec rejects that projection before reaching the output assertions. The parent was asked to use full_projection() for the small one-key fixture, or to request row address explicitly. The two-output case should also assert native.is_some(). Review acceptance of this addition is pending that correction and the test result.

The reviewer later inspected the corrected full_projection() fixture and explicit two-output assertion. The correction is accepted by source inspection. The native Pending test's dataset fixture also now owns Arc<Dataset>, matching basic_full_read's input contract.

## Follow-up: Late Take cancellation

The brief explicitly requires cancellation coverage around the Late Take. Source Pending tests and native task-drop tests exercise different boundaries. The bad-address payload test covers Take failure, not cancellation during a pending Take.

No production cancellation defect was found. MergePayload directly awaits TakeBuilder inside and_then. It introduces no detached task. The merge commits only after its uncommitted execution returns. A narrow Late cancellation test remains necessary to close the explicit evidence requirement.

The parent received a small test pattern using the existing ThrottledStoreWrapper and paused Tokio time. Feed an immediately ready UpdateAll/address input to MergePayload and delay object-store Gets. Poll the payload next future until Pending, drop that future and stream, then check unchanged snapshot contents and release of Take-owned dataset state. This needs no new production hook. Combine this lifecycle test with commit sequencing inspection and the existing failure/retry tests. Do not infer it from a process kill alone.

The reviewer inspected the added payload_pending_take_is_released_on_cancel at payload.rs:238. The fixture first creates an ordinary dataset, then adds the existing throttled-store wrapper. Its immediate input reaches the Take path, where the test requires Pending. It drops the pending next future, stream, and plan. It checks that the wrapped dataset's Weak reference clears, then verifies the original latest manifest and stored row contents. The fixture and API types are correct by inspection. No correction is requested. This closes the source-level Late cancellation gap when the test passes.

The reviewer also checked shared-cache cancellation. The default Session uses QuickCacheBackend. Its loader is awaited in the caller, with a quick_cache placeholder guard. Dropping that guard removes or notifies the unfilled placeholder. It does not preserve a detached loader future for the original scan to inherit. The scheduler spawns onto the current Tokio runtime, and the throttle uses tokio::time::sleep. Source inspection found no definite 60-second real-time wait in the paused test. The actual result remains authoritative.

## Verified final Rust execution evidence

The reviewer read these C-r2 logs after the final optimized test build:

- logs/C-final-unit-tests.log: 357 passed, zero failed, in 0.93 seconds. This includes payload_pending_take_is_released_on_cancel.
- logs/C-native-tests.log: nine passed, zero failed, in 0.03 seconds. Relevant cases include both Pending/drop cases, shared initialization and row completeness, reset/error propagation, and scanner P=2/P=1.
- logs/C-late-lineage-tests.log: 23 passed, zero failed, in 0.05 seconds. This forced-Clate group includes retry and repeated-operation cases.
- logs/C-late-first-seen-tests.log: 21 passed, zero failed, in 0.03 seconds under forced Clate.

These results close the reviewed Rust lifecycle and mechanism test gaps. Python regression results, strict semantic results, the final imported extension identity, and the freeze remain pending.

## Final harness review

The reviewer inspected bench.py, finite.py, first-seen.py, pool.py, and native-extra.py. Their workload data oracles and process isolation remain suitable for the stated comparisons. FirstSeen uses the optimized Rust test binary and explicitly labels its surface as mechanism evidence rather than Python latency. The pool diagnostic checks its expected state and failure consumer. The optional native expansion limits itself to the registered near-threshold comparison and nine total blocks.

A stop-condition defect remains in finite.measured(). It raises validation/source/infrastructure failures only for Ccore, Clate, and Cbudget_late. A Cprep or Cbudget validation failure can therefore continue the automated matrix. Unexpected execution_error is not a stop condition for any variant. The parent was asked to stop invalid candidate modes before expansion. Expected reservation failures must remain separately classified as resource_exhausted. Expected cancellation belongs only to the explicit slow-source diagnostic. Acceptance of the harness remains pending that correction.

Freeze enforcement in finite.main verifies source, harness, and extension hashes. The helper entry points do not all call finite.main. Before running them, the coordinator must verify the same freeze and the explicit Rust test-binary identity where applicable. This is a provenance requirement, not a request for additional performance cases.

The reviewer inspected the corrected finite.measured stop conditions. Validation, infrastructure, source, execution, and unexpected timeout/cancellation now stop every variant. bench.run also classifies a nonzero child exit after execute_returned as infrastructure_error. Both corrections are accepted. No remaining source or harness correction is requested. Final clearance awaits Python regression, strict semantic results, imported extension identity, and the freeze record.

## Visibility-only lint correction

Clippy reported two redundant_pub_crate declarations in candidate.rs: MergeScanPolicy and evidence. The corrected declarations use pub. The containing candidate module remains pub(crate), so neither item becomes externally reachable. The reviewer inspected these declarations and accepts the change.

The existing optimized Rust test results remain valid mechanism evidence for this exact visibility-only difference. No test-binary rebuild is required for it. Freeze the existing test binary with its actual hash, identify its source state as pre-visibility-lint, and preserve the two declaration changes that link it to final source. Its FirstSeen smoke remains mechanism evidence, not a Python latency comparison. The final Python extension must be built from corrected source and pass the planned regression and strict semantic checks.

## Pre-freeze V_sparse fixture correction

The reviewer accepted the revised length generator by inspection. It applies a domain-separated per-row 64-bit mixer and maps the result to inclusive lengths 128 through 2048. Content generation uses its separate RNG seed. This removes the previous 1921-row arithmetic length pattern.

The workload keeps its V_sparse label and selects the new physical fixture V_sparse_r2. Fixture generation, execute/restore, validation, cancellation validation, and warm-file metadata lookup all resolve fixture_name consistently. The parent reported that no V_sparse measurements used the earlier generator. Preserve the old fixture and record the new exact spec and bench.py hash in the freeze. No production algorithm, baseline, resource setting, or acceptance threshold changed.

## Low-memory matrix interpretation

The brief at line 145 stops an OOM configuration/resource cell. Line 185 separately requests Ccore and then eligible Clate for Wn/Ws at the existing low-memory limits. Clate is a distinct configuration. It may run once after Ccore OOM to test whether delayed payload avoids the Early residency cost. The reviewer agrees with removing finite.low's break that skipped this planned case.

Do not repeat the failed Ccore cell. Preserve the failure and report each configuration separately. A Clate success cannot erase Ccore OOM or justify a statement that both configurations are controlled. This interpretation changes no workload, limit, baseline, or acceptance threshold.

## FINAL CLEARANCE

The reviewer clears the reviewed C-r2 source and harness for freezing and the registered mechanism runs. No blocking review finding remains. Formal paired measurements may begin only after their required mechanism gates pass. This clearance is not a claim that performance or low-memory gates already passed.

The reviewer verified these final records:

- Optimized build completed through make/maturin with release-with-debug. The final build log records installation after 16 minutes 32 seconds.
- Python merge regression: 38 passed, 269 deselected, in 4.79 seconds.
- Strict Early/Late semantics: all 12 result files report passed. The harness asserts the actual payload path and Take row counts. The error case records row-prefix fallback before propagating the source error.
- Pool diagnostics: unbounded large input completed, bounded large input failed specifically at HashJoinInput, and bounded small input updated one row. Independent readbacks passed. The failed operation preserved its snapshot.
- Final Clippy completed with warnings denied. The reviewed format check passed.
- Final Rust results remain 357 merge tests, nine native-filter tests, 23 forced-Late lineage tests, and 21 forced-Late FirstSeen tests. Their previously documented source-state exception is limited to two visibility declarations.

The reviewer independently computed all nine changed-source hashes and confirmed that they match pre-freeze-evidence.json. That evidence file has SHA256 f0dc59f0e5287e04c7aab9e5da639fbbbab6685d43b20da0c773f3fb4caf8dd4.

The imported extension is /mnt/lance/checkouts/C/python/python/lance/lance.abi3.so. Its independently checked SHA256 is eefdcab7339d4ebfd1be93d70731cce421d3768e70687f2f2dd4e7068fcb44bb. This matches logs/C-final-identity.json. The Rust test binary SHA256 is 74c9f4089aedc967222ca5f28e41a2dd68a92175a4abc9a733c4951e1632395a. Its exact visibility-only patch is preserved.

The final reviewed harness hashes are:

| File | SHA256 |
| --- | --- |
| bench.py | 946385bfe692cef2a155b91d0e04769994837382747ab07dc847010a014c9947 |
| finite.py | 00d241319ebd30006c00d19c51204b0dce524150fb69c735ad79e6757af7abba |
| semantic.py | 915450e92c29584647058d79c7267c4282d4fe05d30751af61bff507dd2ab39d |
| first-seen.py | 13e7d2c33fbb5f39236f7388c221f0298feed3365f184f1206f9aa18d817c6f7 |
| pool.py | f5f17fbb288a51892ffa8d24fcce0b5e1918d774cd94a83f0007e54e1e0696ac |
| native-extra.py | 22db2ffa81651393e2d7c08655eb0580e26293b139b8dee6f56a64cd70c56ee9 |

Freeze records must match the approved source, extension, test binary, and harness hashes. Preserve earlier failures and the build-cache recovery record. Retain the claim limits documented above, particularly the distinction between Arrow Take memory and physical storage I/O. Changes to measured code, fixtures, thresholds, or oracles after freezing require corresponding review and affected-gate repetition.
