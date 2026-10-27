# Mutation verification

Upstream baseline: 46d7bfdda8ac303d5363c851d6883facb249cb56.
Base implementation: d09358d6f21ea9c360b4663cf5b242deb97d9ebd.

All 13 mutations were rejected by actual test failures. Compilation and setup errors do not count.
Each mutation was applied separately and restored before the next run. Source was restored to the base commit after the runner completed.

| Removed or broken protection | Matching test | Result and evidence |
| --- | --- | --- |
| Remove terminal verified-loss cleanup | `test_owned_indices_after_verified_loss::case_1_verified_absent` | Rejected; [log](logs/mutations/terminal_cleanup.log), [patch](results/mutations/terminal_cleanup.patch) |
| Remove the latest-manifest UUID exclusion | `test_owned_indices_after_verified_loss::case_2_latest_manifest_references_output` | Rejected; [log](logs/mutations/latest_guard.log), [patch](results/mutations/latest_guard.patch) |
| Allow new_id == old_id into the owned inventory | `test_kept_index_survives_concurrent_drop::case_2_owned_commit_boundary` | Rejected; [log](logs/mutations/keep_filter.log), [patch](results/mutations/keep_filter.patch) |
| Omit the incoming compaction FRI UUID | `test_owned_external_fri_after_verified_loss::case_1_v0` | Rejected; [log](logs/mutations/initial_fri.log), [patch](results/mutations/initial_fri.patch) |
| Omit the replacement v0 FRI UUID | `test_owned_fri_rebase_then_terminal_loss::case_1_v0` | Rejected; [log](logs/mutations/rebased_fri.log), [patch](results/mutations/rebased_fri.patch) |
| Omit the tagged assembly UUID | `test_owned_fri_rebase_then_terminal_loss::case_2_tagged` | Rejected; [log](logs/mutations/tagged_fri.log), [patch](results/mutations/tagged_fri.patch) |
| Remove cleanup on the reporter pre-write conflict | `test_owned_indices_preempted_by_delete_before_manifest_write` | Rejected; [log](logs/mutations/prewrite_cleanup.log), [patch](results/mutations/prewrite_cleanup.patch) |
| Remove cleanup on exhausted verified conflicts | `test_owned_indices_after_terminal_conflict::case_1_retries_exhausted` | Rejected; [log](logs/mutations/exhaustion_cleanup.log), [patch](results/mutations/exhaustion_cleanup.patch) |
| Treat caller-owned remap outputs as disposable | `test_borrowed_remap_outputs_survive_verified_loss` | Rejected; [log](logs/mutations/borrowed_remaps.log), [patch](results/mutations/borrowed_remaps.patch) |
| Delete owned directories before an internal retry | `test_owned_fri_rebase_then_terminal_loss::case_1_v0` | Rejected; [log](logs/mutations/cleanup_between_retries.log), [patch](results/mutations/cleanup_between_retries.patch) |
| Turn deletion failure into a fatal error | `test_index_cleanup_delete_failure_preserves_commit_error` | Rejected; [log](logs/mutations/delete_error_is_fatal.log), [patch](results/mutations/delete_error_is_fatal.patch) |
| Continue deleting after the latest-index read fails | `test_index_cleanup_latest_read_failure_preserves_commit_error` | Rejected; [log](logs/mutations/read_error_deletes.log), [patch](results/mutations/read_error_deletes.patch) |
| Run cleanup after a verified landed error | `test_owned_indices_landed_error_keeps_directories` | Rejected; [log](logs/mutations/known_landed_cleanup.log), [patch](results/mutations/known_landed_cleanup.patch) |

The borrowed-remap filter runs two parameter cases. These results describe the base commit plus each saved patch, not the unmodified implementation.
The unmodified implementation passed all 19 new cases and 1,660 affected-module tests; see README.md for tested revisions and commands.
The runner log records final restoration, and each per-mutation log records the source and patch SHA256 hashes.
