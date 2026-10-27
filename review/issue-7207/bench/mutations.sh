#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -lt 2 ]; then
    echo "Usage: mutations.sh SOURCE_ROOT REVIEW_ROOT [MUTATION ...]" >&2
    exit 2
fi
source_root=$(realpath "$1")
review_root=$(realpath "$2")
shift 2
cd "$source_root"
test -n "$CARGO_TARGET_DIR"
git diff --quiet
git diff --cached --quiet
source_revision=$(git rev-parse HEAD)
source_file=rust/lance/src/io/commit.rs
material_dir="$review_root/review/issue-7207"
log_dir="$material_dir/logs/mutations"
patch_dir="$material_dir/results/mutations"
mkdir -p "$log_dir" "$patch_dir"
task_temp=$(mktemp -d "$TMPDIR/issue7207-mutations-XXXXXX")
cp "$source_file" "$task_temp/commit.rs"
restore_source() {
    cp "$task_temp/commit.rs" "$source_file"
}
trap restore_source EXIT
if [ "$#" -eq 0 ]; then
    set -- terminal_cleanup latest_guard keep_filter initial_fri rebased_fri tagged_fri \
        prewrite_cleanup exhaustion_cleanup borrowed_remaps cleanup_between_retries \
        delete_error_is_fatal read_error_deletes known_landed_cleanup
fi
summary="$material_dir/results/mutations.tsv"
if [ ! -f "$summary" ]; then
    printf 'mutation\ttest\tresult\tbase_commit\n' > "$summary"
fi
for mutation_name in "$@"; do
    case "$mutation_name" in
        terminal_cleanup) test_filter=test_owned_indices_after_verified_loss::case_1_verified_absent ;;
        latest_guard) test_filter=test_owned_indices_after_verified_loss::case_2_latest_manifest_references_output ;;
        keep_filter) test_filter=test_kept_index_survives_concurrent_drop::case_2_owned_commit_boundary ;;
        initial_fri) test_filter=test_owned_external_fri_after_verified_loss::case_1_v0 ;;
        rebased_fri) test_filter=test_owned_fri_rebase_then_terminal_loss::case_1_v0 ;;
        tagged_fri) test_filter=test_owned_fri_rebase_then_terminal_loss::case_2_tagged ;;
        prewrite_cleanup) test_filter=test_owned_indices_preempted_by_delete_before_manifest_write ;;
        exhaustion_cleanup) test_filter=test_owned_indices_after_terminal_conflict::case_1_retries_exhausted ;;
        borrowed_remaps) test_filter=test_borrowed_remap_outputs_survive_verified_loss ;;
        cleanup_between_retries) test_filter=test_owned_fri_rebase_then_terminal_loss::case_1_v0 ;;
        delete_error_is_fatal) test_filter=test_index_cleanup_delete_failure_preserves_commit_error ;;
        read_error_deletes) test_filter=test_index_cleanup_latest_read_failure_preserves_commit_error ;;
        known_landed_cleanup) test_filter=test_owned_indices_landed_error_keeps_directories ;;
        *) echo "Unknown mutation: $mutation_name" >&2; exit 2 ;;
    esac
    restore_source
    perl "$material_dir/bench/mutate.pl" "$mutation_name" "$source_file"
    patch_file="$patch_dir/$mutation_name.patch"
    git diff -- "$source_file" > "$patch_file"
    log_file="$log_dir/$mutation_name.log"
    if {
        printf 'Base commit: %s\nMutation: %s\nTest: %s\n' "$source_revision" "$mutation_name" "$test_filter"
        sha256sum "$source_file" "$patch_file"
        cargo test --locked --profile ci -p lance --lib "$test_filter" -- --nocapture
    } > "$log_file" 2>&1; then
        result=0
    else
        result=$?
    fi
    restore_source
    git diff --exit-code -- "$source_file"
    if [ "$result" -eq 0 ]; then
        echo "SURVIVED $mutation_name: the matching test unexpectedly passed" >&2
        exit 1
    fi
    if ! rg -q '^test result: FAILED\.' "$log_file"; then
        tail -60 "$log_file" >&2
        echo "INVALID $mutation_name: compilation or setup failed before the test result" >&2
        exit 1
    fi
    if ! rg -F "$test_filter" "$log_file" | rg -q 'FAILED'; then
        tail -60 "$log_file" >&2
        echo "INVALID $mutation_name: the expected test did not fail" >&2
        exit 1
    fi
    printf '%s\t%s\trejected\t%s\n' "$mutation_name" "$test_filter" "$source_revision" >> "$summary"
    printf 'REJECTED %s by %s\n' "$mutation_name" "$test_filter"
done
restore_source
git diff --exit-code
trap - EXIT
rm "$task_temp/commit.rs"
rmdir "$task_temp"
printf 'Source restored to %s\n' "$source_revision"
