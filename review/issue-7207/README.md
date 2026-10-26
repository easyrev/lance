# Issue 7207: research and approval gate

Upstream baseline: `46d7bfdda8ac303d5363c851d6883facb249cb56`.

This branch contains research, not an implementation ready for an upstream PR.
Work stopped before the proposed public `IndexRemapper` method, as task section 10 requires.
No upstream PR or GitHub comment was created.

## Branches

| Role | Branch | Commit |
| --- | --- | --- |
| Pure | `fix/7207-reclaim-lost-commit-indices` | `46d7bfdda8ac303d5363c851d6883facb249cb56` (no implementation yet) |
| Review | `review/7207-reclaim-lost-commit-indices` | The commit containing this README, obtainable with `git rev-parse review/7207-reclaim-lost-commit-indices` |
| Upstream baseline | `upstream/main` | `46d7bfdda8ac303d5363c851d6883facb249cb56` |

The final handoff records the exact review commit and remote verification.
Existing #10096 branches were inspected without modification.

## Findings and decision

Read [DESIGN.md](DESIGN.md) for line-level evidence, all commit error exits, ownership, replay, overlap, and planned tests.

The verified-loss arms still remove only transaction files.
The reporter's preempted Rewrite returns before a manifest write and never reaches those arms.
Control flow proves that this invocation did not publish, but deletion also needs exclusive ownership of the index directories.

Generic Rewrite and CreateIndex transactions are replayable.
Custom remappers have no exclusive-ownership contract.
The recommended fix adds a provided `IndexRemapper::owns_remapped_indices()` method, defaulting to false.
Only the built-in remapper initially opts in. This public API addition needs approval before implementation.

An alternative changes only private code and covers default `compact_files` calls.
It excludes remap outputs from public/distributed `commit_compaction`, even with the built-in remapper.
Both options can preserve generic replay inputs and track FRI entries minted during rebase.

## Environment

Requested host: ecs.g9a.4xlarge, 16 vCPU, 64 GiB RAM, ESSD disks.
The shell reports 16 CPUs and 61 GiB of memory. The ECS SKU and disk class were supplied by the task, not queried from cloud metadata.
The repository is on a 49 GiB system filesystem. `/mnt/lance` is a 295 GiB data filesystem with about 196 GiB available.
`sccache` is installed at `/usr/local/bin/sccache`.

Future build shells must use:

```bash
export CARGO_TARGET_DIR=/mnt/lance/target-issue-7207
export RUSTC_WRAPPER=/usr/local/bin/sccache
```

No build directory was populated and no long-running job was started.
The sandbox mounts `.git` read-only, so the authorized fetch and branch operations used escalation.
The managed-environment status tool and `/etc/codex/network-policy.json` were unavailable in this executor.
GitHub reads succeeded through the escalated CLI. No credentials were inspected.

## Results by revision

| Revision | Check | Result |
| --- | --- | --- |
| `46d7bfdda8ac303d5363c851d6883facb249cb56` | Static code and GitHub research | Completed for the design decision |
| Same baseline | Regression tests / baseline red tests | Not run: stopped before implementation |
| Same baseline | Clippy / fmt / rustdoc / module tests | Not run: no source change |
| No fixed revision exists | Mutation tests | Not run |
| Baseline and fixed revision | IVF_PQ race, lost commits, orphan count/bytes, wall time | Not measured |

The tests and commands in DESIGN.md are plans, not execution evidence.
In particular, retention tests for Keep and landed-error should be baseline-green.
No failed test log or benchmark script is presented as a reproduction.

## Reproduction and branch checks

Reproduce the static investigation with the baseline checkout and the source references in DESIGN.md.
GitHub discussion snapshots and branch overlap results are under `results/`.

Run the separation check locally:

```bash
python3 review/issue-7207/check_separation.py
```

Run it against fetched remote tracking refs:

```bash
python3 review/issue-7207/check_separation.py \
  origin/fix/7207-reclaim-lost-commit-indices \
  origin/review/7207-reclaim-lost-commit-indices
```

The checker requires no review path in pure, pure as an ancestor of review,
and review-only differences under `review/issue-7207/`.
Logs identify the revisions checked. The final handoff reports the post-publication check.

## Files

- `DESIGN.md`: findings, exact API proposal, alternative scope, and planned tests.
- `PR.md`: explicitly incomplete PR outline. Do not submit it.
- `check_separation.py`: local and remote branch separation check.
- `logs/environment.log`: disk, memory, CPU, and sccache observations.
- `logs/fetch.log`: upstream fetch output.
- `logs/separation.log`: separation check at the research checkpoint.
- `results/issue7207.json`, `comments7207.json`: issue and claim/reply snapshots.
- `results/pr8118.json`, `comments8118.json`: prior PR description and both discussion comments.
- `results/10096-*`: unchanged branch refs and overlap diff.
- `results/overlap.json`: file lists for inspected related PRs.
- `results/recent-commits.txt`: recent commits touching the commit code.

The host has no build or measurement job from this investigation and can be released while the design awaits a decision.
