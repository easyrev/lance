# Harness h1 review

## FINAL CLEARANCE

The reviewer accepts the h1 cleanup correction and recovery of the existing W_dense Ccore run. No blocking defect remains in this change. Create the new freeze checkpoint with harness-r0/freeze.json as its parent. Keep the source revision C-r2 and preserve the original review-r2.md.

This review inspected the patch, current bench.py, cleanup tests and their output, recovery notes, partial worker metrics, recovered metrics, cleanup record, and original resource events. The reviewer did not run a workload, build, or edit source.

## OOM recovery

The original resource events establish confirmed OOM independently of the later cleanup error:

- The cell began with zero OOM counters.
- The child exit code was -9 and timeout was false.
- memory.peak reached 8589934592 bytes, the configured 8 GiB limit.
- oom_kill increased to three and oom_group_kill increased to one.

metrics-before-recovery.json preserves the partial worker state. The recovered metrics report confirmed_oom, validated=false, and no merge_seconds. The manifest retains the failed run ID and records seconds=null. No workload re-execution occurred. cleanup-recovery.json records populated=0 before removal of the leftover group.

This is a valid negative resource result. It denies controlled-memory claims for this configuration/resource cell. Its RSS samples are incomplete lower-bound observations. It must not enter successful latency or validation denominators.

## Correction assessment

The patch retries only EBUSY from group removal. It bounds that retry by five seconds and records removal, emptiness, and attempt count separately from workload status. Other cleanup errors still propagate. The workload exit and resource counters are saved before attempting cleanup, so cleanup cannot erase those observations.

Before creating another worker, isolated checks all existing benchmark groups and rejects any populated group. An empty group that remains busy after the retry cannot overlap a live earlier workload with a new measurement. The six tests exercise immediate removal, transient EBUSY, persistent EBUSY, another errno, an empty prior group, and a populated prior group. logs/cleanup-tests.log reports all six passed.

The correction changes code before process creation and after process exit. It does not change the merge timer, source generation, fixture, validation oracle, resource settings, or measurement loop. Earlier valid timings remain usable with their original harness identity. New planned runs carry harness_revision=h1.

## Continuation scope

- Do not repeat W_dense Ccore at this resource setting.
- The unstarted eligible dense Clate cell may run once. It is a distinct configuration. Preserve either its success or its failure independently.
- Continue the previously authorized Late, fixed-low, and slow-source cells after the failed worker group is empty. Respect the existing no-repeat and semantic-stop rules.
- Do not calculate a valid dense latency ratio against the failed Early run. A later Clate success cannot erase the Ccore OOM or justify a blanket controlled-memory claim.
- No numerical threshold, baseline, workload, or resource amendment is authorized by this review.

## Verified identities

The preserved review-r2.md hash still matches the original freeze record. The current Python extension hash also matches the original C-r2 freeze.

| Artifact | SHA256 |
| --- | --- |
| harness-r0/freeze.json | 45cef8f03060f3c27c75f8a5f1591badc62867b695cdfe2ccaa92e7d7b6812cf |
| diagnostics/review-r2.md | b225cee73587e8dcea32afa512752a30bf770346af763d9519717f85cbe762ce |
| diagnostics/harness-h1.patch | cfba2d8b41f4ed7a0eb88d90743f7202310aa445b03f843fdcdf114012b9d3ac |
| bench.py | 02a622859145d5865e796d0c689f929515748a24fd1717d8a6bab01d8be00c3e |
| C Python extension | eefdcab7339d4ebfd1be93d70731cce421d3768e70687f2f2dd4e7068fcb44bb |

The new freeze checkpoint must preserve the original source, binary, workload, and unaffected harness hashes. Update only the approved harness and review metadata, with this report linked as h1 clearance.
