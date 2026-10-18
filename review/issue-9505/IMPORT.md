# ECS import and provenance

## Branch and tested identity

- Review branch: `review/9505-merge-insert-investigation`.
- Pure branch for this candidate: none.
- Restored implementation commit: `f68d9e88d5ba4d45aa1317fba9b3eb973479826c`.
- Original base: `dc53d5d174af62c49ddd98d1024a64488c1e4404`.
- Tested identity: C-r2, the base plus `results/20261018T103247Z-C-r2/C.patch`.

All nine restored source files match `freeze.json`. The frozen patch passes a reverse-application check against this checkout. All 2630 entries in the original C-r2 artifact catalogue match their original hashes. The test executable predates two visibility-only corrections. The original report and `test-binary-to-final-visibility.patch` preserve that qualification. The Python extension includes those corrections.

No benchmarks or builds ran during this import. Existing ECS test and lint logs remain the validation evidence. Local checks cover source identity, archive integrity, Git patch consistency, evidence counts, links, and credential patterns. The local pre-commit launcher points to an unavailable environment. These archival commits bypass that launcher to preserve the frozen source and raw evidence without automatic rewrites. This import does not claim a new local build, workspace-wide Clippy pass, or validation against current main.

## Original paths

The source checkout was `/mnt/lance/checkouts/C`.
The evidence root was `/mnt/lance/validation-9505`.
The archived `results/` directories map directly to that root's `results/` directories.
The `inputs/` directory preserves both original task documents, the executed prompt, the environment handoff, and the historical profile.mk helper.

Absolute ECS paths inside raw records remain unchanged. Reproduction requires those paths or an explicitly adapted runner. Do not rewrite historical records when preparing another environment.

The C-r2 `fixtures` symlink now points to `../20261018T092212Z-C-r1/fixtures`. `import/ecs-export.json` records its original target. That directory contains metadata only. Regenerate data from the preserved workload definitions and scripts before execution. Relative run aliases retain their original targets.

## Reconstructed P

The exact reconstructed commit is `90d981870c960e3bb55bfa46b206853ea4282fdb`. Equivalence to historical P remains unverified. The source bundle preserves the reconstruction and its required new history:

```sh
git bundle verify review/issue-9505/baselines/P_reconstructed.bundle
git fetch review/issue-9505/baselines/P_reconstructed.bundle HEAD
```

The bundle requires base commits `dc53d5d174af62c49ddd98d1024a64488c1e4404` and `8d77df617e85687567e9529fbc5520f793783e78`. Both were present during verification. Fetching the bundle exposes the original reconstruction as FETCH_HEAD without publishing another branch.

## Evidence integrity

`import/ecs-export.json` records original file hashes, excluded paths, and the relocated fixture link. `import/local-verification.json` records import checks. `SYMLINKS.json` records packaged links. `SHA256SUMS` covers all regular files except itself. Raw byte hashes remain separate from Git object IDs.

This archive omits generated fixture data and Python bytecode. This archive contains no credentials, SSH keys, account authentication files, virtual environments, compiled extensions, or build targets. Original C source archives remain as small source snapshots.
