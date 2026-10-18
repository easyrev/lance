# Harness h1 correction

The original frozen harness and freeze are preserved in harness-r0/. Source,
compiled binaries, workloads, limits, timers, cache, validation oracles and
acceptance criteria are unchanged. No compilation occurred.

W_dense Ccore at1GiB pool/8GiB cgroup was killed by cgroup OOM. The saved raw
execute-resource-events.json proves oom_kill3, oom_group_kill1 and peak8589934592.
The old coordinator then raised EBUSY on immediate group.rmdir. It had already
saved the exit and resource counters but had not reached final classification.
The traceback remains in logs/late-smoke.log. The partial worker metrics remain
as metrics-before-recovery.json. The recorded terminal status is confirmed_oom,
validated=false, no returned execute, and no latency value. RSS samples remain
lower bounds. The workload was not re-executed.

After verifying populated=0 and an empty process list, the coordinator removed
the leftover group. cleanup-recovery.json records that check. The corrected
harness retries only EBUSY, for at most5seconds, and saves cleanup outcome
separately from workload outcome. It also refuses any new isolated worker while
an earlier benchmark group is populated. Persistent empty groups can remain
without losing the saved workload result. Other cleanup errors still raise.
Six tests exercise the actual AST blocks; logs/cleanup-tests.log passed.

New runs carry harness_revision=h1. Previous runs used r0. Earlier valid timings
are unaffected because this change runs before process creation or after exit,
outside the merge timer. No existing measurement is repeated. A new freeze
checkpoint will preserve the original freeze as its parent and update only
harness/review metadata. The source revision remains C-r2.

Dense Early OOM is a valid negative resource result, not a candidate pass.
The corresponding distinct forced Late cell, fixed-low and slow-source cells
can proceed only after the reviewer accepts this correction. No valid dense
latency ratio can be computed against failed Early. No limits or thresholds
will change and failed configuration/resource cells will not be repeated.
