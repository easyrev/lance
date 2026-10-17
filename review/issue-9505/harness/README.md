# Lance #9505 investigation harness

This is an experimental comparison, not a release or acceptance claim. Run it
on the isolated ECS workspace at `/mnt/lance/issue-9505`.

## Revisions

- Unmodified upstream main: `dc53d5d174af62c49ddd98d1024a64488c1e4404`.
- Candidate A: the accompanying patch against that main; only
  `rust/lance/src/dataset/write/merge_insert.rs` changes.
- PR #10077 head: `9e1ebc2e816a7195b56757ebe269e74989fc30c7`.
- PR #10077 merged with main for comparison:
  `f8859373d5022eedea239db2fcfd68713a423762`.

The `main`, `fix`, and `pr10077` directories are independent Git worktrees. No
existing #7895 or #9617 checkout or build directory is changed. Build caches were
copied into this investigation's own target directories.

## Build and run

Follow each checkout's `AGENTS.md` and `python/AGENTS.md`. The first Python command
in each fresh worktree was `make install`, using the repository's optimized
`release-with-debug` Cargo profile, including ThinLTO. The exact override was:

```sh
. /mnt/lance/env.sh
. /mnt/lance/proxy.sh
proxy-on
export CARGO_TARGET_DIR=/mnt/lance/issue-9505/target
cd /mnt/lance/issue-9505/main/python
make install UV_SYNC='uv sync --frozen --config-settings-package "pylance:build-args=--profile release-with-debug --locked"'
```

Repeat the prescribed install in `fix/python` and `pr10077/python`. Keep the
successful build logs under `logs/`. Do not run performance tests while builds
are active. `matrix.sh` waits for the PR build and rejects active Cargo/rustc jobs.

Generate each fixture once using the main worktree's environment:

```sh
uv run --no-sync python ../../harness/harness.py generate \
  --uri ../../data/fixed-4000000 --rows 4000000 --columns 44 \
  --output ../../results/gen-fixed-4000000.json
```

Use absolute dataset paths when running `run.sh`, which starts a separate
systemd unit. The generated matrix fixtures are:

| Name | Target | Source used by the matrix |
| --- | --- | --- |
| fixed-4000000 | 4M rows, 44 int64 columns, 40 fragments | 100 rows, key + 2 replacement fields |
| fixed-16000000 | 16M rows, 44 int64 columns, 160 fragments | same |
| fixed-64000000 | 64M rows, 44 int64 columns, 640 fragments | same |
| reverse | 100K rows, 44 int64 columns, 4 fragments | 3M rows, all columns; update + insert |
| wide | 400 rows, 3 int64 fields + 2 large-binary fields, 16 fragments | 25 rows, key + a 10 MiB replacement binary |

Generate the reverse fixture with `--rows 100000 --columns 44 --fragment-rows
25000`. Generate wide with `--rows 400 --columns 3 --binary-bytes 5242880
--batch-rows 4 --fragment-rows 25`. Wide target rows each have an independent
5 MiB binary payload and an empty replacement field. The integers and binary
bytes come from seeded random generators. The fixture is synthetic, not a copy
of the original reporter's dataset.

`bash /mnt/lance/issue-9505/harness/matrix.sh` runs both source forms twice per
case. It also runs separate plan diagnostics and memory-limited cases. To rerun
one case:

```sh
/mnt/lance/issue-9505/harness/run.sh fix custom-repeat 2G 268435456 execute \
  --uri /mnt/lance/issue-9505/data/fixed-4000000 --source streaming
```

The third positional argument is the cgroup hard limit; the fourth is
`LANCE_MEM_POOL_SIZE` in bytes. Swap is disabled for each unit. Every operation
restores version 1 before measurement. Failed runs can leave unreferenced data
files; the original version remains available.

## Measurement contract

- Each invocation starts a fresh process. Target files are pre-read outside the
  measured cgroup. These are warm local-storage measurements, not cold-cache or
  object-store results. The default allocator is used.
- `seconds` measures `builder.execute`, including planning, stream consumption,
  writing, and commit. It excludes dataset generation, restoration, and result
  validation. Materialized input preparation is recorded separately in
  `source_prepare_seconds`; their sum is also recorded. A streaming full-schema
  source generates batches on demand during execution.
- The RSS monitor samples every 10 ms. `process_peak_rss_bytes` is Linux
  `ru_maxrss`, so it also includes source preparation. Anonymous/file RSS and
  cgroup `memory.current`/`memory.peak` are sampled directly. A systemd summary
  after a successful exit can underreport the child process peak; use the direct
  counters and process RSS. Shared file pages can belong to another cgroup, so
  cgroup usage and process RSS are different quantities.
- The `.rss.jsonl` file is flushed on every sample. It survives an OOM kill; its
  observed peak is then a lower bound. `.journal` confirms kernel OOM kills.
  A wrapper exit code alone is not proof of the underlying failure mode.
- CPU time is sampled around the merge call. `average_cpu_cores` is CPU seconds
  divided by wall seconds, not a count of configured threads. Throughput is
  logical target or source rows per merge second, not physical scan throughput.
- Successful execute runs validate updated/inserted/deleted counts, total row
  count, and partial-update values. Analyze runs are labeled `diagnostic`:
  current Lance's analyze helper swallows stream errors, so a returned plan
  does not establish successful execution.
- `.explain.txt` is a schema-only streaming plan. `.plan.txt` comes from a separate
  analyze invocation with the real source form; inspect operator rows and memory
  metrics to interpret it. Do not use a materialized source's schema-only explain
  output as its actual execution plan.
- Files named `causal-*` or `wide-causal` were diagnostic runs made during builds.
  They establish completion/failure and plan behavior, not comparable throughput.

## Verification already completed

- `cargo fmt --all`.
- `cargo test -p lance --lib dataset::write::merge_insert -- --test-threads=4`:
  335 passed, including the added 8 MiB-pool regression.
- `cargo clippy --all --tests --benches -- -D warnings`: passed.
- `uv run --no-sync pytest python/tests/test_dataset.py -k merge_insert -q`:
  38 passed, 269 deselected.
- Harness: Ruff format and check passed.

The candidate is still experimental. In particular, its wide streaming
counterexample still OOM-kills with a 1 GiB pool and a 2 GiB cgroup. Do not submit
this patch as a complete fix based only on the passing functional tests.
