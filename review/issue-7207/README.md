# Issue 7207: Option B implementation review

Original upstream baseline: 46d7bfdda8ac303d5363c851d6883facb249cb56.

This implementation uses private ownership tracking. The public IndexRemapper trait and all public signatures remain unchanged.
The user requested a new branch pair because the original remote pair is an independent control group. See CONTROL.md.

## Branches

| Role | Branch | Commit |
| --- | --- | --- |
| Pure implementation | fix/7207-reclaim-lost-commit-indices-option-b | d09358d6f21ea9c360b4663cf5b242deb97d9ebd |
| Review | review/7207-reclaim-lost-commit-indices-option-b | The commit containing this report; use git rev-parse with the branch name |
| Original upstream baseline | upstream/main at investigation start | 46d7bfdda8ac303d5363c851d6883facb249cb56 |
| Control pure, preserved | origin/fix/7207-reclaim-lost-commit-indices | 02d6ed30dc995d9c5420a51ce1d23da89d020bc5 |
| Control review, preserved | origin/review/7207-reclaim-lost-commit-indices | 297b020bfb582938e2b785a406800f750e9aaf4b |

The final handoff records the review commit and verifies both new remote refs.
The control group and both #10096 branches are preserved. No upstream PR or GitHub comment is created.

## Design and scope

DESIGN.md contains the Phase 1 source references, every commit error exit, UUID producers, replay analysis, and overlap table.
The ordinary LanceDB table.optimize path passes remap_options=None in both the reporter's 0.30.1 release and the inspected current main.
The exact revisions and source excerpts are in results/lancedb-optimize-path.md.

The commit layer collects IDs from an internal, call-local ownership policy:

- compact_files with remap_options=None owns the built-in remapper's fresh outputs.
- Public commit_compaction and calls with a supplied remapper preserve remap outputs for caller replay.
- Compaction owns the FRI entry it creates locally.
- Every successful rebase contributes its fresh FRI UUID, including tagged assembly entries that are absent from the transaction.
- Generic Rewrite and CreateIndex inputs remain caller-owned.

Cleanup runs on terminal verified foreign/absent outcomes, conflict exhaustion, and verified-loss retry timeouts.
The reporter's check_txn rejection also gets cleanup: no manifest write started in that iteration, and only verified losses can reach another iteration.
No index cleanup runs between retries, after a landed commit, or after an unknown outcome.

The helper reads the latest manifest and its complete index list inside cleanup, then excludes referenced UUIDs.
Keep IDs are never eligible. Read failure skips deletion. Delete failure is logged without replacing the commit error.
The helper deletes only candidate _indices/UUID prefixes, never data files or external row-map directories.

## Evidence by tested revision

| Revision | Result |
| --- | --- |
| 9f5c301849c164fe60ee34167b6138e671f9df32, tests only on baseline production code | 6 expected leak regressions fail; 10 safety cases pass; logs/red.log |
| Same tests-only revision | 1,651 module tests pass, the same 6 regressions fail, 1 existing test is ignored; logs/baseline-modules.log |
| 35be8cd539d65d28e60d6addc497e543132a960a, historical implementation | 19 new cases pass; 1,660 module tests pass and 1 is ignored |
| d09358d6f21ea9c360b4663cf5b242deb97d9ebd | Clippy all targets passes; logs/clippy.log |
| Same final implementation | Rustdoc with warnings denied passes; logs/rustdoc.log |
| Same final implementation | 1,660 module tests pass, including all 19 new cases; 1 existing test is ignored. Formatting passes. See logs/fixed-modules-final.log and logs/fmt-check-final.log |
| Same final implementation after restoring every mutation | 1,660 module tests pass, 0 fail, 1 existing test is ignored; logs/post-mutation-modules.log |
| Same final implementation plus individual saved patches | All 13 mutations rejected by actual matching test failures; source restored to the final implementation. See MUTATIONS.md, results/mutations.tsv, and logs/mutation-run.log |

The final implementation adds three private-boundary safety cases after the baseline test checkpoint:
owned-policy Keep eligibility, terminal conflict exhaustion, and retry timeout.
The original retention tests are correctly baseline-green. No claim is made that all safety tests fail on main.

The historical 35be8cd results are not proof for the later future-size correction.
That correction boxes internal commit futures after Clippy detected large writer futures.
The complete final checks and mutation logs identify their actual tested commit.
Earlier fixture/type-check logs are diagnostics, not red-regression evidence.

## Commands and environment

Requested host: ecs.g9a.4xlarge, 16 vCPU, 64 GiB RAM, ESSD disks.
Observed: 16 CPUs, about 61 GiB memory, repository on a 49 GiB system filesystem, and a 295 GiB data filesystem at /mnt/lance.
The task supplied the ECS SKU and disk class; they were not queried from cloud metadata.

Rust 1.98.1 follows rust-toolchain.toml. Existing Cargo and sccache caches are reused.
CARGO_TARGET_DIR=/mnt/lance/targets/issue7207 keeps build outputs off the system disk.
RUSTC_WRAPPER=/usr/local/bin/sccache uses the installed compiler cache.
The repository's ci profile is used without ad hoc LTO changes.
The host's exact environment exports are in /mnt/lance/results/issue7207/env.sh.

Run from the pure checkout with that environment:

    cargo test --locked --profile ci -p lance --lib dataset::optimize::tests::index_cleanup -- --nocapture
    cargo test --locked --profile ci -p lance --lib -- dataset::optimize io::commit dataset::write::commit dataset::tests
    cargo clippy --locked --profile ci -p lance --all-targets -- -D warnings
    cargo fmt --all --check
    RUSTDOCFLAGS='-D warnings' cargo doc --locked --profile ci -p lance --no-deps

Run the separation checker:

    python3 /path/to/review/issue-7207/check_separation.py

Pass the two origin/Option-B refs as positional arguments to check the published refs.
The checker verifies that pure has no review/issue-* paths, pure is an ancestor of review,
and all differences are under review/issue-7207/.

The temporary /tmp review checkout and scratch logs were lost when the host restarted.
The committed tests survived. Final red evidence was regenerated, and active logs now live in the persistent review checkout.

## Mutation verification

bench/mutations.sh removes one component at a time, runs its matching test, and restores source after every run.
Each log names the base commit, test, source hash, and saved patch hash.
A compile failure does not count as a rejected mutation.
All 13 mutations were rejected. See MUTATIONS.md for the protection-to-test mapping, bench/README.md for commands, and results/mutations.tsv for raw results.

## Optional end-to-end measurement

Not measured. No concurrent IVF_PQ storage-growth result is claimed for this implementation or the control group.
The optional end-to-end race was not attempted; the required evidence is the deterministic Rust regression suite.

| Revision | Lost commits | Unreferenced index directories | Orphan bytes | Wall time |
| --- | --- | --- | --- | --- |
| Original upstream baseline | Not measured | Not measured | Not measured | Not measured |
| Option B implementation | Not measured | Not measured | Not measured | Not measured |
| Independent control group | Not measured | Not measured | Not measured | Not measured |

## Limitations and maintainer questions

Generic CreateIndex, caller-owned Rewrite inputs, custom/public remap outputs, and partial builds remain outside automatic reclamation.
A failure before a builder returns metadata can still leave untracked directories.
Data files remain excluded because replayed RewriteResult paths can belong to an earlier committed attempt (#7722).
The FTS half-written directory that becomes active is a separate failure.

PR.md includes the requested follow-up question about an explicit remapper ownership contract (Option A).
No public trait addition is included here.

## File list

- DESIGN.md: research, control-flow proof, ownership/replay analysis, and overlap.
- PR.md: upstream PR draft for review only.
- CONTROL.md: independent control refs and source-revision boundary.
- MUTATIONS.md: each removed protection and the regression test that rejected it.
- check_separation.py: local and remote branch separation check.
- bench/mutate.pl and bench/mutations.sh: mutation definitions and runner.
- bench/README.md: verification usage and measurement status.
- logs/: raw baseline, final verification, and mutation output.
- results/: source snapshots, #10096 PR1/PR2 overlap, control refs, mutation patches, and summary.
