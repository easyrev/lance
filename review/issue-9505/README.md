# Issue #9505: review package

This branch contains the tested implementation and its investigation records.
The implementation is also on `fix/9505-small-stream-statistics`. The additional
commit on `review/9505-small-stream-statistics` contains only this directory.
No GitHub pull request or upstream comment has been posted.

## Review target

| Object | Revision |
| --- | --- |
| Upstream main at the investigation baseline | `dc53d5d174af62c49ddd98d1024a64488c1e4404` |
| Candidate B: small-stream statistics | `793e4e27119540a17ae37ce78d4f5f4d52060a93` |
| PR #10077 head used in the comparison | `9e1ebc2e816a7195b56757ebe269e74989fc30c7` |
| PR #10077 merged with the baseline for testing | `f8859373d5022eedea239db2fcfd68713a423762` |
| Rejected candidate A: source-first join | `ddb00c9c0c8c5271a8ca4187df1d84c583a8f5e2` |

Start with the implementation diff, then use the records below to challenge its
correctness, resource bounds, and scope:

```sh
git diff dc53d5d174af62c49ddd98d1024a64488c1e4404 \
  793e4e27119540a17ae37ce78d4f5f4d52060a93 -- \
  rust/lance/src/dataset/write/merge_insert.rs \
  python/python/lance/dataset.py python/python/tests/test_dataset.py
```

The implementation changes three files. It prepares exact statistics for small
non-indexed sources and uses Lance's bounded execution context. It retains
DataFusion's join selection and partitioning. It does not change indexed joins.
The production source in this checkout is the review target; patches are retained
as historical records, including the rejected experiment.

## Evidence and reproduction

- [REPORT.md](REPORT.md): conclusions, measured results, validation, and limits.
- [DESIGN.md](DESIGN.md): report context, call chain, alternatives, and source links.
- [REPRODUCE.md](REPRODUCE.md): fixtures, commands, environment, and measurement contract.
- [PR_DRAFT.md](PR_DRAFT.md): an unpublished, scoped PR description.
- [results/runs.csv](results/runs.csv) and [results/summary.csv](results/summary.csv): individual runs and summaries.
- [results/](results/): raw execution results, plans, RSS samples, and OOM journals.
- [logs/](logs/): builds, checks, and intermediate failures, with distinct filenames.
- [evidence/](evidence/): captured public issue, PR, and review material.
- [harness/](harness/): generation, measurement, and analysis scripts.
- [manifest.json](manifest.json): revisions and publication scope.

The reproduction scripts retain the measured Linux layout at
`/mnt/lance/issue-9505`. They require independent worktrees, the prescribed Python
setup, and systemd cgroup access. On a fresh host, prepare that layout and copy
`harness/` there; use fresh `results/` and `logs/` directories. The environment
and proxy scripts named in the build instructions are host setup, not bundled
credentials. Adapt those host paths if needed. Do not run the historical pipeline
scripts merely to read these records: they build code and execute workloads.
Datasets and binaries are excluded; generate fixtures with the supplied harness.

The measurements are a historical snapshot, not a claim about a later upstream
revision. There are 160 formal execute runs: 134 validated successes, 16 memory
pool errors, and 10 journal-confirmed OOM kills. Plan diagnostics and files named
`causal-*`, `wide-causal`, or under `validation-errors/` are not successful formal
benchmark runs. Most cases have two repetitions; each extreme 2 GiB wide-cell
case has one. Fixtures are synthetic. The original reporter's private data was
not available. See the measurement contract before comparing RSS, pool usage,
and cgroup counters.

The frozen candidate passed 337 Rust merge tests, 42 Python merge tests, two plan
doctests, full workspace Clippy, formatting, and Python lint. The source hashes
are in [logs/statistics-source.sha256](logs/statistics-source.sha256). Run this
from the repository root to check that this checkout contains the tested source:

```sh
sha256sum -c review/issue-9505/logs/statistics-source.sha256
```

`ARTIFACTS.sha256` records the packaged files. Verify it from this directory with
`sha256sum -c ARTIFACTS.sha256`. Raw records are preserved; duplicate full source
snapshots are omitted because the implementation and rejected patch are already
available. Packaging changes navigation, publication metadata, and these review
instructions. The plot script also received formatting-only changes from the
repository hook. No measured values were changed.

## Questions for an independent review

1. Does bounded prefetch preserve EOF, errors, batch order, and every row when a
   batch crosses 100 MiB or 128 Ki rows? One caller batch can exceed either limit.
2. Do FirstSeen deduplication and retry behavior preserve the existing contract,
   including `spill_for_retry(false)` and validation before the first source poll?
3. Do tests adequately cover join types, matched and unmatched rows, NULLs,
   partial updates, duplicate handling, and conflicts across fragments?
4. Is the bounded execution context appropriate for the non-indexed path? A
   DataFusion pool is not a process RSS limit, and HashJoin pool exhaustion does
   not automatically spill to disk in the tested version.
5. Is the observed workload benefit enough to justify this scope? Unknown large
   streams and underestimated wide target statistics can still choose a costly
   build side. Extreme wide cells still OOM under the tested 2 GiB cgroup limit.
6. Is an independent PR useful alongside #10077? The candidate preserves a
   benefit for large sources and small targets; #10077 is faster in the measured
   small-source, large-target cases. No combined candidate plus reduced #10077
   implementation was tested. Maintainer acceptance and a safe split of #10077
   have not been established.

Keep observed results, source-based explanations, and untested hypotheses
separate. Review findings can recommend a different scope or integration with
#10077; an independent PR is not a required conclusion.

## Two-branch workflow

For each issue, keep a pure PR branch for upstream code, tests, and necessary
project documentation. Keep a review branch with the same implementation plus
investigation material for other reviewers. This directory belongs only on the
review branch.

Make implementation fixes on the pure branch first, then bring those commits
into the review branch and update its evidence. Never merge the review-only
commit into the pure branch. Compare the implementation revisions explicitly
when tests or results change. Branch publication alone does not authorize a PR,
an upstream comment, or messages to other agents.
