# Issue #9505: deferred merge payload

This review-only branch preserves the final ECS candidate and its benchmark evidence. No pure PR branch exists for this candidate.
The implementation commit is `50e216972e1558ce253bece5db462d8241fde96a`. Its base commit is `0a0d327082988018a25f56147d3b6d02f6c79ecc`.

## Start here

- [Final summary](results/killer-merge-final-20261019/summary.json): recorded results and paired comparisons.
- [Original ECS audit](results/killer-merge-final-20261019/audit-results.json): live checks of source, binaries, fixtures, and recorded results.
- [Final runbook](results/killer-merge-final-20261019/README.md): workloads, measurement boundaries, commands, and limits.
- [Import record](IMPORT.md): source identity, test-source exception, integrity checks, and path mapping.

## Implementation and evidence

The measured variant `K` maps to `/mnt/lance/checkouts/K_check`. The implementation commit preserves its three changed source files byte for byte.
It defers omitted target columns until an update needs their values. It reuses values already read for conditions.
It also carries the planning context into execution. The final candidate removes the intermediate join admission selector.

The final matrix contains 45 new executions, each with a separate successful output-validation record.
Four additional cells reference one historical baseline OOM. Those references contain no new timing samples.
Wn and Ws each have three same-block comparisons between K and the unchanged baseline.
Their median K-row-rewrite/baseline-row-rewrite time ratios are 0.07025 and 0.39344.
F16 has no valid same-round baseline time ratio. K column rewrites use an existing writer option, not a single-mechanism ablation.
These results describe the recorded local hot-cache workloads.

## Archive structure

| Directory under `results/` | Role |
| --- | --- |
| `killer-merge-final-20261019` | Final selector-free K measurements and audit |
| `killer-merge-no-admission-20261019` | Selector removal experiment, final build logs, and tests |
| `killer-merge-20261018` | Earlier K experiment and the original baseline OOM |
| `killer-merge-admission-check` | Intermediate selector investigation and failure evidence |
| `killer-merge-admission-fixed-20261019` | Intermediate selector correction experiment |
| `first-principles-9505-20261018` | Earlier comparison of historical candidates and writer modes |

`source-snapshots/` preserves the final patch and export-time copies of the implementation and test checkouts.
Each result retains its own freeze. Intermediate snapshots and measurements describe different code revisions.
The [previous C investigation](https://github.com/easyrev/lance/tree/8500fb5a0c0d162884b9e1d36cd3926bddc2c7c6/review/issue-9505) remains on its original branch.

Original evidence bytes and relative symlink targets remain unchanged. The archive excludes generated datasets, environments, caches, compiled extensions, bytecode, and runtime locks.
Generator scripts, fixture specifications, and hash manifests remain available. Archived commands describe historical runs and supply no new authorization.

Run `python3 review/issue-9505/import/verify-archive.py` to check the packaged hashes and links.
The separate evidence-only audit also passed locally. Its output is [local-artifact-audit.json](import/local-artifact-audit.json).
No benchmark, build, dataset validation, or Rust/Python code lint ran locally for this import.
