# Lance #7895: ChatGPT review materials

Branch `easyrev/lance:codex/issue-7895-reviewed-candidate` contains the candidate code and its review evidence. The user designated this branch for ChatGPT review. A final merge branch has not been prepared. This publication does not create or update a pull request.

The measured code candidate is [`26632629ca162cdbfd82dabad1d80e3e6c92b364`](https://github.com/easyrev/lance/commit/26632629ca162cdbfd82dabad1d80e3e6c92b364). Its official upstream base is `4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9`. Later commits on this branch package review materials under this directory. They do not change the tested implementation.

Start with the [delivery report](reports/delivery-report.md), then read the [performance report](reports/performance-report.md) and [final independent evidence review](reports/independent-performance-final.md). Review the [code comparison](https://github.com/easyrev/lance/compare/4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9...26632629ca162cdbfd82dabad1d80e3e6c92b364) separately from this evidence directory.

## Report index

| Report | Purpose |
| --- | --- |
| [Delivery report](reports/delivery-report.md) | Implementation, support boundaries, validation results, evidence links, and remaining choices |
| [Source contracts](reports/source-contracts.md) | Independent source inspection before the permitted Phase 1 comparison |
| [Python contract review](reports/python-contract-review.md) | Source adapters, input behavior, and Python API contracts |
| [First independent review](reports/independent-review-first.md) | Initial findings and the evidence available at that stage |
| [Revision review](reports/independent-review-revision.md) | Error propagation fix, independent probes, and completed correctness checks |
| [Phase 1 comparison](reports/phase1-comparison.md) | Source boundary, chronology, and the resulting conflict-test revision |
| [Performance script audit](reports/independent-performance-script-audit.md) | Independent examination of the measurement method |
| [Audit response](reports/performance-audit-response.md) | Changes that address measurement concerns |
| [Performance report](reports/performance-report.md) | Final measurements, ranges, negative results, and limitations |
| [Performance interpretation](reports/performance-interpretation.md) | Evidence-supported conclusions and unresolved causes |
| [Final independent performance review](reports/independent-performance-final.md) | Independent recomputation and artifact verification |
| [Maintainer tradeoffs](reports/independent-maintainer-tradeoffs.md) | API and default-policy choices that remain for review |
| [Measurement instructions](reports/README.md) | Recorded build, fixture, probe, and measurement commands |
| [Recovery record](reports/RECOVERY.md) | Historical completion state and retained artifacts |
| [English PR draft](evidence/pr-draft.txt) | Unpublished title and body, provided as review material |
| [Permitted Phase 1 source report](evidence/phase1-allowed-report.txt) | The exact reference used after the independent candidate, tests, and first review |

## Evidence and validation

The [evidence directory](evidence/) contains all 960 files from the original review archive. Reports, scripts, logs, patches, and raw observations remain byte-identical. GitHub-readable report copies in `reports/` add a historical-stage note and adapt Markdown links. They preserve the original findings and results.

Historical statements such as “unpublished,” “outside the repository,” and “performance results pending” describe the stage when each report was written. The final reports include completed performance measurements. The user later authorized this review-branch publication. Historical task and permission statements do not replace the current review request.

- [Final correctness and lint evidence](evidence/review-final/), [root core test](evidence/root-core-tests.log), and [root workspace Clippy](evidence/root-workspace-clippy.log).
- [Build provenance](evidence/performance-build-provenance.json), [native artifact index](evidence/native-snapshots.json), and [candidate source verification](evidence/candidate-python-source-verification.json).
- [120 primary measurements](evidence/raw/), [comparison data](evidence/performance-comparisons.json), [14 final mechanism controls](evidence/controls/final/), and [actual plans](evidence/plans/).
- [20 separate measurements without the probe](evidence/no-probe-followup/), their [summary](evidence/no-probe-followup-summary.json), and the [independent recomputation](evidence/independent-performance-check.json).
- [Final candidate patch](evidence/final-candidate.patch), [pre-Phase 1 patch](evidence/pre-phase1.patch), and [revision probe results](evidence/independent-review-revision-probe.json).

Correctness checks used the recorded DEV extension. Final performance measurements used matched `release-with-debug` artifacts. The [native artifact index](evidence/native-snapshots.json) identifies their different hashes. Full Python and Rust test suites, remote CI, and remote-storage performance were not run.

Eligible sources avoided replay storage in the measured cases. Small-input latency and actual-retry CPU/RSS costs remain in the reports. Random retry backoff limits conclusions about total retry latency. These results do not establish a general speed or memory improvement.

## Integrity and reproduction

The [original archive](candidate-review-bundle.tar.gz) has SHA256 `0c882262f73998860a58ea252f51e32d2fb48eb2ae6c63a6a6371970a5d24543`. Its [receipt](review-bundle-receipt.json) records the original code candidate and file count. The [original manifest](evidence/review-bundle-manifest.json) hashes 959 evidence files and excludes itself. The [publication manifest](publication-manifest.json) hashes every published file in this directory except itself, including the readable report copies.

The code patch SHA256 is `9694eb0eaf38d30a9ea87556163b4403ea88d7a4b54e0da6d8e8907306658ed5`. Its tree is `266fe35ffdb06144ba73a255ef8d51e13ba32516`. These identifiers refer to the measured code candidate, before this directory was added.

Native binaries and dataset payloads remain excluded from Git. Reproduction requires rebuilding the pinned revisions and regenerating fixtures. Archived scripts retain their original `/workspace` paths and require the documented environment. Recorded hashes identify the original artifacts and do not guarantee identical bytes from a new build.

No implementation changed during report packaging, and no implementation tests were rerun for it. Packaging checks verify archive hashes, report completeness, link targets, and an unchanged code tree. Raw evidence must retain its original bytes, so formatting hooks must not rewrite archived scripts or logs.
