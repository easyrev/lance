# Lance #9505 investigation harness

This is a local investigation, not a release or acceptance claim. Run it
on the isolated ECS workspace at `/mnt/lance/issue-9505`.

## Revisions

- Unmodified upstream main: `dc53d5d174af62c49ddd98d1024a64488c1e4404`.
- Candidate A (`fix`): commit `ddb00c9c0c8c5271a8ca4187df1d84c583a8f5e2`; only
  `rust/lance/src/dataset/write/merge_insert.rs` changes.
- PR #10077 head: `9e1ebc2e816a7195b56757ebe269e74989fc30c7`.
- PR #10077 merged with main for comparison:
  `f8859373d5022eedea239db2fcfd68713a423762`.
- Candidate B (`statistics`): branch `fix/9505-small-stream-statistics`, commit
  `793e4e27119540a17ae37ce78d4f5f4d52060a93`. See [REPORT.md](REPORT.md) for results
  and scope, and [PR_DRAFT.md](PR_DRAFT.md) for the unpublished draft.

The `main`, `fix`, `pr10077`, and `statistics` directories are independent Git worktrees. No
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

Repeat the prescribed install in the other worktrees. Keep the
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
| wide-small-source | Same wide target | 25 rows, key + two int64 replacement fields |
| source-100k | The 4M-row fixed target | 100K rows, key + two int64 replacement fields |
| wide-variable | 2M rows, 20 fragments, independent binary payload lengths uniformly sampled from 128 B to 2 KiB | 100 rows, key + two int64 replacement fields |

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

## Candidate A verification

- `cargo fmt --all`.
- `cargo test -p lance --lib dataset::write::merge_insert -- --test-threads=4`:
  335 passed, including the added 8 MiB-pool regression.
- `cargo clippy --all --tests --benches -- -D warnings`: passed.
- `uv run --no-sync pytest python/tests/test_dataset.py -k merge_insert -q`:
  38 passed, 269 deselected.
- Harness: Ruff format and check passed.

Candidate A was rejected as a complete fix. In particular, its wide streaming
counterexample still OOM-kills with a 1 GiB pool and a 2 GiB cgroup. Do not submit
this patch as a complete fix based only on the passing functional tests.

## Candidate B workflow

The statistics candidate stops pulling batches when buffered arrays exceed
100 MiB or 128 Ki rows. It publishes statistics only after EOF.
One caller batch can cross either bound. The 100 MiB value reuses the existing
retry buffer budget. It is not a hard process memory limit.

After Rust edits, use the repository build entrypoint with the supplied profile
override. The extra makefile adds the required benchmark profile and `--locked`
to the existing Maturin command:

```sh
cd /mnt/lance/issue-9505/statistics/python
uv run --no-sync make -f Makefile -f ../../harness/profile.mk build \
  UV_RUN='uv run --no-sync'
```

An intermediate build became obsolete when the source bound changed. It was
cancelled before any benchmark. Its log is `statistics-build-superseded.log`.
The final Python regression checks a 100K-row reader, so it detects a binary
that still uses the earlier 1 MiB bound.

Run candidate B and the additional comparisons after builds and checks finish:

```sh
bash /mnt/lance/issue-9505/harness/statistics-matrix.sh
bash /mnt/lance/issue-9505/harness/boundary-matrix.sh
bash /mnt/lance/issue-9505/harness/wide-variable-matrix.sh
```

The second script covers the 100K-row source. These scripts include real-source
plan diagnostics. The first also compares wide targets with narrow sources
across all four variants. Each regular case has two runs. Wide cases with a
2 GiB cgroup have one run each.

The third script generates and measures the moderate variable-width fixture.
Its binary content and per-row lengths are independently generated with seed
9505. This supplements the 5 MiB-cell stress case; it is also synthetic and does
not establish the field types used by the original reporter.

From the candidate root, with `CARGO_TARGET_DIR` set to this investigation's
`target-test` directory:

```sh
cargo fmt --all
cargo test -p lance --lib dataset::write::merge_insert -- --test-threads=4
cargo clippy --all --tests --benches -- -D warnings
```

From its Python directory:

```sh
uv run --no-sync make lint
uv run --no-sync pytest python/tests/test_dataset.py -k merge_insert -q
uv run --no-sync pytest --doctest-modules python/lance/dataset.py \
  -k 'explain_plan or analyze_plan' -q
```

Use the final validation report and logs for results. Intermediate failures are
retained with distinct log names. `statistics-source.sha256` records the frozen
source files used for the final build and checks.

## Supplemental conditions

The ECS host has 16 vCPUs on an Intel Xeon Platinum 8369B and nominal 128 GiB RAM.
Linux reports 132804042752 bytes of physical memory. It runs Ubuntu 24.04 with
kernel 6.8.0-139-generic. Builds use Rust 1.98.1 and CPython 3.12.3. The repository
config targets Haswell with AVX2, FMA, and F16C. `release-with-debug` uses ThinLTO
and 16 codegen units for every measured variant.

The reverse high-memory case uses an 8 GiB pool and a 16 GiB cgroup. To repeat it:

```sh
/mnt/lance/issue-9505/harness/run.sh main reverse-custom 16G 8589934592 execute \
  --uri /mnt/lance/issue-9505/data/reverse --full-schema \
  --source-rows 3000000 --source streaming
```

Repeat for each variant and input form. Use unique run IDs to retain earlier
results and avoid mixing systemd journal entries. The historical supplemental
script also reran two main wide cases after correcting their validation query.
The original validation failures remain under `results/validation-errors`.

The CSV includes input preparation plus merge latency as
`prepare_and_merge_seconds`. Medians use successful runs only, with all statuses
shown alongside them. Two repeats establish reproducible effects, not narrow
confidence intervals. Regenerate the CSV from raw results with:

```sh
cd /mnt/lance/issue-9505/main/python
uv run --no-sync python ../../harness/summarize.py ../../results \
  > ../../results/summary.json
```

The final patch is `patches/small-stream-statistics.patch`; the rejected
source-first experiment is kept separately. To regenerate the scaling chart
from this delivery directory (Matplotlib is the only extra dependency):

```sh
uv run --no-project --with matplotlib python harness/plot_scaling.py .
```
