# Verification scripts

Baseline: 46d7bfdda8ac303d5363c851d6883facb249cb56.

mutations.sh removes one safety component at a time, runs its matching regression test,
records the exact patch and source hash, and restores the source after every run.
Compilation errors do not count as a rejected mutation.
Source must start clean. The script inherits the documented Rust environment and uses the repository's ci profile.

Run from a shell with Cargo and the data-disk CARGO_TARGET_DIR configured:

    bash /path/to/review/issue-7207/bench/mutations.sh SOURCE_ROOT REVIEW_ROOT

Pass mutation names after the two roots to run a subset.
Results belong to the recorded base commit plus each saved mutation patch.
They are not test results for the unmodified source.

The optional concurrent IVF_PQ end-to-end measurement has not been run.
These scripts validate regression coverage and do not measure table growth or production performance.
