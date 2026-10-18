Execute the research agent's benchmark plan for Lance #9505 candidate C on this ECS. Your primary deliverable is reproducible evidence for the research agent's subsequent analysis. Continue through implementation, tests, measurements, and the final report.

Read these files first:

- /mnt/lance/validation-9505/lance-9505-unified-design.md
- /mnt/lance/validation-9505/codex-ecs-validation.md
- /mnt/lance/RESTORED-ENVIRONMENT.md
- /root/.agents/skills/rust-best-practices/SKILL.md
- /root/.agents/skills/asd-ste100/SKILL.md

The main design defines algorithms and scope. The task brief defines execution and acceptance. The handoff records the current environment. Preserve these three documents.

Use $rust-best-practices during implementation and review. Repository AGENTS.md and the experiment requirements take precedence over generic skill advice. Use $asd-ste100 for progress updates and reports.

Load /mnt/lance/env.sh and /mnt/lance/proxy.sh. Run proxy-on.

Use existing U/B/C/P worktrees and frozen baselines. Label reconstructed P as P_reconstructed. Do not claim equivalence to the missing historical P.

Implement C in /mnt/lance/checkouts/C. Reuse verified caches through the repository workflow. Use release-with-debug for benchmarks.

Follow the documented gates and finite matrix. Complete correctness and mechanism checks before formal measurements.

Before formal measurements, spawn one reviewer subagent. Require read-only review of the final diff, design correspondence, and test coverage. Prioritize semantics, error propagation, cancellation, resource sharing, execution paths, and fair comparisons. Wait for the review.

Correct defects that invalidate experiments. Repeat affected tests and obtain another review of the corrections. Style suggestions must not block experiments. Freeze the reviewed source and binaries before measurements.

Complete the applicable paired comparisons and Early/Late experiments. If native performance fails its retention threshold, continue the documented Cbudget+Late comparison. Expand only under documented conditions and existing authorization. Do not compile during measurements. Run one performance case at a time.

Resolve routine choices independently. Correct implementation and harness defects without changing the research contract. If a correction requires different questions, baselines, resource limits, or acceptance criteria, pause the affected branch. Record evidence and proposed amendments for the research agent. Continue unaffected experiments.

If a hard gate fails, stop expansion for that revision. Preserve failures before corrections. Repeat affected experiments under a new revision after corrections. Do not move thresholds to claim success.

Treat valid negative results as completed experiments, not candidate passes. Correct invalid experiments before you repeat them.

Create a unique directory under /mnt/lance/validation-9505/results/. Continuously save progress, raw results, failures, hashes, review findings, and recovery commands. Produce all required deliverables. Report each gate and remaining limitations. Distinguish historical evidence, new measurements, inferences, and unverified claims. Do not create a PR or publish upstream comments.
