# Candidate C review, revision 1

Review date: 2026-10-18. This is a read-only source and harness review. The reviewer did not build, run tests, or run performance cases. The parent agent owns those checks. The reviewer used the rust-best-practices and asd-ste100 skills.

Reviewed inputs: repository guidance, the unified design, the ECS validation brief, the current tracked diff, candidate.rs, stats_guard.rs, exec/payload.rs, bench.py, and semantic.py. Source edits continued during this review. The diagnostics correction described below is included in the latest inspection.

## Decision

Do not start formal measurements yet. Correct the input-validation defect and complete the listed mechanism checks. No definite wrong-result defect was found in the payload gathering or shared native task stream by source inspection. This statement does not replace execution evidence.

## Blocking defects and evidence gaps

### 1. Invalid source schemas can be consumed before reporting a missing join key

Files: rust/lance/src/dataset/write/merge_insert.rs:2520 and :3152.

prepare_resources validates the write sink and asks can_use_create_plan whether the source qualifies. That method accepts is_subset_schema without requiring source_has_key_columns. A source containing only an existing non-key field therefore qualifies for preparation. stream_source_to_provider then polls that source before create_plan constructs the join and reports the missing key.

This breaks the Gate 1 contract that schema errors precede the first source side effect. An invalid source that stays Pending can wait indefinitely instead of returning its known schema error.

Correction: validate every source join key before preparation polls the reader. Report the missing names and the source schema. Check condition parsing and other schema-only validation at this boundary as well. Add an execution-entry test with a missing-key schema and a source poll counter. Assert the expected error and zero polls.

### 2. Required optimizer and native cancellation checks are absent from the reviewed tests

Files: rust/lance/src/dataset/write/merge_insert/stats_guard.rs:110, logical_plan.rs:354, and rust/lance/src/io/exec/filtered_read.rs:4059.

The guard test checks direct and registry statistics. It does not pass the bytes-only counterexample and dual-Absent case through normal Auto join optimization. The current native test checks successful shared initialization and row completeness. It does not cover a worker error or cancellation while workers hold or await tasks.

The validation brief explicitly requires these checks before measurements. In particular, wrapper getter tests cannot establish that the final Auto plan avoids the unsafe target collect decision. Successful row collection cannot establish cancellation or failure completion.

Correction: add a plan-only counterexample with synthetic statistics for 200 wide target rows and an unknown source. Show the bytes-only failure and dual-Absent protection through the actual optimizer and registry paths. Check the small_fixed_target model immediately below and above its threshold. Add native worker-error and downstream-cancellation tests with deterministic completion and task-drop assertions. Preserve ordinary optimizer rules.

The external semantic harness also needs an assertion that each supported Clate case reaches MergePayload. Its output oracle alone would still pass if Clate silently used Early. Inspect candidate.jsonl or execution metrics and assert payload path selection plus expected take-row counts. Error tests must distinguish preparation failure from an error after the prefix fallback reaches execution.

### 3. Detailed C-only instrumentation contaminated the timed path, now corrected in source

Files: rust/lance/src/dataset/write/merge_insert.rs:2923 and :2980. Harness: bench.py:507.

The initially reviewed source rendered full physical plans and formatted operator metrics inside execute. It evaluated those strings even if evidence output was disabled. B and P did not do that work. This conflicted with the measurement contract for separate detailed diagnostics.

The parent agent corrected the source during review. Both renderings now require LANCE_MERGE_DIAGNOSTICS. Source inspection accepts that correction. Rebuild the corrected binary before freezing it.

bench.py copies its entire parent environment. Explicitly remove LANCE_MERGE_DIAGNOSTICS for formal runs. Use a separate diagnostic invocation to enable it. Record the effective flag in the run manifest. This prevents an inherited flag from silently restoring the unequal work.

## Measurement and claim limits

- MergePayload uses TakeBuilder directly. payload_take_arrow_bytes counts returned Arrow memory, not physical storage bytes. The plan's scan_take_bytes aggregate does not automatically include the separate TakeBuilder operation. Do not report this aggregate as complete physical early-versus-late I/O. Add a scoped I/O counter if that claim is needed, or report the narrower row and returned-memory evidence explicitly.
- semantic.py exercises duplicate target keys, null keys, null payload, inserts, deletes, conditions, Fail, empty input, and a source error. Its expected row contents are suitable for those cases. It does not yet establish FirstSeen, a Take failure, cancellation, or conflict-retry behavior for the new payload node.
- bench.py validates all scalar fields and binary contents, uses distinct update values, and preserves a physical row_marker for duplicate-key wide cases. These are valid oracle choices. The benchmark's actual path, native output count, selected build side, and pool enforcement still need Gate 2 evidence.
- Formal Cbudget/Ccore comparisons must use the same resolved P, rows sizing, I/O settings, and fixture snapshot. The source structure supports that comparison. The report must confirm the actual optimized path rather than infer native use from the experiment label.
- Retry rebuilds the plan against the refreshed dataset, but MergeResources remains from the initial snapshot. Its file-width estimate can therefore remain stale after a conflict. This is a soft-model limitation, not evidence of a hard memory bound. Record it or recompute affected target estimates during retry.

## Non-blocking suggestions

- MergeInsertWriteNode::PartialEq and Hash include deferred_target_columns, but PartialOrd does not. Include that field in the ordering chain so distinct nodes do not compare equal by ordering alone.
- Resource evidence hardcodes revision C-r1. Update or derive it when creating a corrected revision, so logs identify the frozen source accurately.

## Accepted design correspondence from source inspection

- Prefix preparation preserves the crossing batch and unread tail. It publishes complete statistics only after observed EOF. The batch cap stops without an additional EOF poll.
- FirstSeen keeps the complete small input in encounter order before deduplication. Prefix evidence does not become a fabricated full-source row estimate.
- StatsGuard masks both rows and bytes and retains the default Unknown cardinality effect. It delegates execution, rebuild, native repartitioning, and filter pushdown without adding a queue.
- The initial join policy uses the actual target child schema and global row evidence. It calls the public swap_inputs API and retains normal optimizer processing.
- Native output construction reuses the existing shared running_stream and task stream. Each native output awaits one task outside the task-stream lock. It does not introduce a buffered(N) window per output.
- MergePayload requires SinglePartition and performs one serial Take per input batch. It gathers by physical addresses from the operation snapshot, checks returned cardinality, and leaves insert/delete/Nothing rows without a payload Take.

Before measurement, obtain another review of corrections and the completed mechanism evidence. Preserve this report as the first-review record.
