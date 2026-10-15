# Independent review history

This report reconstructs findings from independent agent messages in this task.
The reviews occurred during working-tree development. They were not all performed against the final committed SHA.
This is a summary, not a verbatim review transcript or external maintainer approval.
The final candidate for subsequent review is `09d2c8a0deff51d59b77a83f68d54fed2c277710`.

| Finding | Response in the candidate | Supporting evidence |
| --- | --- | --- |
| PQ source, concatenation, and transposition could exceed a two-copy estimate | Release source batches after concatenation; use quantizer-aware estimates and account for remapping | Four 4/8-bit PQ conversion cases in the final builder log; two storage ownership tests |
| Optional offsets could prevent an otherwise valid partition from obtaining capacity | Add cache eviction and an asynchronous admission reclaimer | Shuffler eviction/window tests and scheduler reclaimer tests |
| A large pool could still be constrained by the fixed 128 MiB shuffle target | Derive a larger target from finite pool capacity | `test_shuffle_memory_large_pool_sets_larger_batch_target` |
| Polling the next input could retain an unadmitted batch beside a nearly full buffer | Flush proactively near the target; disclose upstream/current input outside the accounting | `test_shuffle_flushes_near_limit_batch_before_polling_lookahead` |
| Fixed row counts could make wide multivector input fail unnecessarily | Apply scan byte targets before decoding, including append and precomputed scans; size split/join materialization | Two final wide-input cases and `raw_vector_fetch_budget_bounds_materialized_buffers` |

The lookahead change mitigates an overlap; it does not make all upstream allocations part of the pool contract.
Earlier follow-up reviews reported no new confirmed P1/P2 defects in the inspected shuffler/cache, scheduler, and storage paths.
Those messages covered targeted static checks, not an exhaustive correctness proof.

The [validation report](validation-report.md) maps the test claims to raw logs and records their provenance limits.
The [package audit](package-audit.md) is a separate independent audit performed while publishing these reports.
It checks evidence and selected source claims. It must not be presented as a complete re-review of all changed implementation code.

## Remaining reviewer questions

- Do all conversion and fragment-reuse paths retain reservations for their complete buffer lifetimes?
- Does a shared pool behave acceptably when capacity is held by unrelated consumers with no wake-up notification?
- Are the documented RSS exclusions and minimum-working-set errors acceptable for the intended public API?
- Does the current scratch-file integration sufficiently address #7308, or should remaining historical goals become a separate follow-up?

The reports provide evidence for these questions without presuming upstream agreement.
