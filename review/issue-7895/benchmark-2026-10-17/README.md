# PR #9617 benchmark review bundle

This bundle contains the evidence needed to review the benchmark design, raw results, H1-H6 decisions, and root-cause analysis for Lance PR #9617.

## Recommended review order

1. `pr9617-scaling-brief.md` — preregistered questions, matrix, stop rules, and required deliverables.
2. `results/summary.md` — conclusions, limitations, root-cause evidence, and the PR-ready English Performance section.
3. `results/env.md` — machine, revisions, toolchain, dataset, and integrity metadata.
4. `results/raw.jsonl` — all 288 measured runs.
5. `harness/`, `results/runs/`, `logs/`, and `results/profiles/` — implementation and supporting evidence.
6. `results/pr.patch` — the exact rebased PR delta measured by this benchmark.

## Revision identity

- Upstream: `dc53d5d174af62c49ddd98d1024a64488c1e4404`
- Public PR head: `ff576648ac969f0379400748c987c29d986a288f`
- Locally rebased PR: `e18df5f4708b42be99aa33ec9ac12de15401982f`
- Original/rebased stable patch ID: `12bf58d204d22624576c3e68b2cbfa0917cd3e33`

## Integrity snapshot

- Raw records: 288
- Successful and verified: 287
- Expected failure: one upstream restricted-TMP `ENOSPC` run
- `raw.jsonl` SHA-256: `3e96fc039eec46f3541bd5288acd2fa4017d06d6169c05c0620005b44a5a4d8e`
- `MANIFEST.sha256` covers every other file in this bundle.

## Deliberate exclusions

The bundle excludes generated datasets, source worktrees, virtual environments, Cargo targets, temporary files, and raw binary profiler recordings (`*.perf.data`, `*.heaptrack.zst`). Human-readable profiler reports, profiler metadata, pool diagnostics, per-run logs, and RSS timelines are included. The binary recordings remain on the benchmark host if a lower-level forensic review is later needed.

No PR code was modified during measurement. Nothing was pushed and no GitHub comment was posted.
