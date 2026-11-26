# Issue 10526: reader-sliced-and-mixed-bridging — execution record

Handoff: [handoff.md](handoff.md) (verbatim). This record states facts only; reviewers judge them.

## Branches and commits

| Role | Ref | Commit |
| --- | --- | --- |
| Pure PR | none — review-only stage (implementation commit on this branch) | `64b5fb31843561e4dc0a14dbdf71ba26decb6049` |
| Review | `review/10526-reader-sliced-and-mixed-bridging` | HEAD of this branch |
| PR1 baseline | `origin/perf/fullzip-variable-shared-buffers` | `d4cac03c93e441e5f3299d8a3a00ffe4365e98f1` |
| Upstream baseline | `upstream/main` | `83593e1ad` |
| Upstream PR | not opened | — |

Sibling approaches: `review/10526-wide-value-page-split`, `review/fullzip-variable-shared-buffers`.

## Environment

See [results/environment.txt](results/environment.txt). Summary:
- Machine: `lance-ecs`, AMD EPYC 9T24 (64 CPUs, 1 socket, 32 cores × 2 threads), 247 GiB RAM, Debian 6.12.113+deb13-amd64, glibc 2.41.
- Toolchain: `rustc 1.98.1`, `cargo 1.98.1`, Python 3.12.16, profile `release-with-debug`.
- Runtime settings: `LANCE_CPU_THREADS=64`; all `MALLOC_*` variables unset.

## Commands run

```bash
# Rust checks (on lance-ecs, /tmp/killer-proto/src)
CARGO_TARGET_DIR=/tmp/killer-proto/target CARGO_BUILD_JOBS=24 cargo fmt --all
CARGO_TARGET_DIR=/tmp/killer-proto/target CARGO_BUILD_JOBS=24 cargo clippy -p lance-encoding --tests --profile release-with-debug -- -D warnings
CARGO_TARGET_DIR=/tmp/killer-proto/target CARGO_BUILD_JOBS=24 cargo test -p lance-encoding --profile release-with-debug
CARGO_TARGET_DIR=/tmp/killer-proto/target CARGO_BUILD_JOBS=24 cargo test -p lance-file --profile release-with-debug --lib

# Python native extension build (on lance-ecs, /tmp/killer-proto/src/python)
CARGO_TARGET_DIR=/tmp/killer-proto/target TMPDIR=/tmp/killer-proto/tmp \
  UV_PROJECT_ENVIRONMENT=/tmp/killer-proto/venv VIRTUAL_ENV=/tmp/killer-proto/venv \
  UV_CACHE_DIR=/tmp/killer-proto/tmp/uv-cache XDG_CACHE_HOME=/tmp/killer-proto/tmp/xdg-cache \
  CARGO_BUILD_JOBS=24 RUSTC_WRAPPER="" \
  uv run --frozen --no-sync maturin develop --uv --profile release-with-debug

# Interleaved fresh-process read & repeat benchmarks (on lance-ecs)
python3 /tmp/killer-proto/tmp/run_bench.py
```

## Results

### Data structure observations (IPC inputs and `.lance` outputs)

- `/dev/shm/lance-10526/ipc/wide-repeated.arrow`: 8,000 rows, 100 distinct prefixes in contiguous runs (`runs=100, min_run=80, max_run=80`). `.lance` file size: `base=491,019,071` bytes vs `final=20,642,169` bytes.
- `/dev/shm/lance-10526/ipc/wide-clustered.arrow`: 25,000 rows, 50 distinct prefixes in contiguous runs (`runs=50, min_run=500, max_run=500`). `.lance` file size: `base=1,534,448,835` bytes vs `final=29,506,372` bytes.
- `/dev/shm/lance-10526/ipc/wide-unique.arrow`: 25,000 rows. `.lance` file size: `base=1,534,797,507` bytes vs `final=1,534,818,518` bytes.

### Rust and Arrow IPC verification

See [results/rust-checks.txt](results/rust-checks.txt):
- `cargo fmt --all`: exit code 0.
- `cargo clippy -p lance-encoding --tests --profile release-with-debug -- -D warnings`: exit code 0.
- `cargo test -p lance-encoding --profile release-with-debug`: 2646 ok, 0 failed, 3 ignored; doc-tests: 8 ok, 0 failed, 1 ignored.
- `cargo test -p lance-file --profile release-with-debug --lib`: 477 ok, 0 failed, 0 ignored.
- Arrow IPC scan (`to_batches(batch_size=1024)`) and `take(128, seed=10526)` equality checks on all 8 wide datasets (`base` and `final`): 16/16 equal, exit code 0.

### Interleaved read & repeat benchmarks (default glibc, `LANCE_CPU_THREADS=64`)

Builds compared:
- `base`: `cb8c25692` reading `p2/<ds>/base`
- `pr1`: `d4cac03c9` reading `p2/<ds>/final`
- `killer`: `64b5fb318` reading `p2/<ds>/final`
- `killer_on_base`: `64b5fb318` reading `p2/wide-unique/base`

| Metric | Build | Tested commit | Runs | Median | Min–max | Raw data |
| --- | --- | --- | --- | --- | --- | --- |
| `wide-unique` scan wall (ms) | base | `cb8c25692` | 7 | 749.52 | 671.96–820.76 | `results/bench_results.json` |
| `wide-unique` scan wall (ms) | pr1 | `d4cac03c9` | 7 | 554.23 | 539.05–721.79 | `results/bench_results.json` |
| `wide-unique` scan wall (ms) | killer | `64b5fb318` | 7 | 351.54 | 334.00–377.60 | `results/bench_results.json` |
| `wide-unique` scan RSS (MiB) | base | `cb8c25692` | 7 | 5861.23 | 5374.00–5991.66 | `results/bench_results.json` |
| `wide-unique` scan RSS (MiB) | pr1 | `d4cac03c9` | 7 | 4681.52 | 4239.85–6425.80 | `results/bench_results.json` |
| `wide-unique` scan RSS (MiB) | killer | `64b5fb318` | 7 | 5777.78 | 5375.67–6064.61 | `results/bench_results.json` |
| `wide-unique` cold take(128) wall (ms) | base | `cb8c25692` | 5 | 33.09 | 32.50–33.30 | `results/bench_results.json` |
| `wide-unique` cold take(128) wall (ms) | pr1 | `d4cac03c9` | 5 | 34.78 | 34.56–35.18 | `results/bench_results.json` |
| `wide-unique` cold take(128) wall (ms) | killer | `64b5fb318` | 5 | 30.74 | 30.52–31.42 | `results/bench_results.json` |
| `wide-unique` cold take(128) RSS (MiB) | base | `cb8c25692` | 5 | 211.28 | 209.16–212.04 | `results/bench_results.json` |
| `wide-unique` cold take(128) RSS (MiB) | pr1 | `d4cac03c9` | 5 | 204.60 | 203.41–205.47 | `results/bench_results.json` |
| `wide-unique` cold take(128) RSS (MiB) | killer | `64b5fb318` | 5 | 201.84 | 200.81–203.00 | `results/bench_results.json` |
| `wide-unique` repeat1024 first (ms) | base | `cb8c25692` | 5 | 200.28 | 199.85–202.51 | `results/bench_results.json` |
| `wide-unique` repeat1024 first (ms) | pr1 | `d4cac03c9` | 5 | 215.76 | 215.40–218.67 | `results/bench_results.json` |
| `wide-unique` repeat1024 first (ms) | killer | `64b5fb318` | 5 | 192.38 | 191.17–194.59 | `results/bench_results.json` |
| `wide-unique` repeat1024 first (ms) | killer_on_base | `64b5fb318` | 5 | 190.39 | 190.02–191.50 | `results/bench_results.json` |
| `wide-unique` repeat1024 calls 6–20 (ms) | base | `cb8c25692` | 5 | 193.73 | 193.17–194.16 | `results/bench_results.json` |
| `wide-unique` repeat1024 calls 6–20 (ms) | pr1 | `d4cac03c9` | 5 | 202.06 | 201.79–203.61 | `results/bench_results.json` |
| `wide-unique` repeat1024 calls 6–20 (ms) | killer | `64b5fb318` | 5 | 184.90 | 184.36–186.55 | `results/bench_results.json` |
| `wide-unique` repeat1024 calls 6–20 (ms) | killer_on_base | `64b5fb318` | 5 | 183.85 | 183.61–184.76 | `results/bench_results.json` |
| `wide-unique` repeat1024 proc RSS (MiB) | base | `cb8c25692` | 5 | 597.01 | 595.30–599.34 | `results/bench_results.json` |
| `wide-unique` repeat1024 proc RSS (MiB) | pr1 | `d4cac03c9` | 5 | 581.30 | 580.73–582.72 | `results/bench_results.json` |
| `wide-unique` repeat1024 proc RSS (MiB) | killer | `64b5fb318` | 5 | 582.68 | 580.83–583.25 | `results/bench_results.json` |
| `wide-unique` repeat128 calls 6–20 (ms) | base | `cb8c25692` | 5 | 21.43 | 21.40–21.67 | `results/bench_results.json` |
| `wide-unique` repeat128 calls 6–20 (ms) | pr1 | `d4cac03c9` | 5 | 22.09 | 21.68–22.41 | `results/bench_results.json` |
| `wide-unique` repeat128 calls 6–20 (ms) | killer | `64b5fb318` | 5 | 21.39 | 21.35–21.52 | `results/bench_results.json` |
| `wide-unique` repeat128 proc RSS (MiB) | base | `cb8c25692` | 5 | 241.46 | 241.20–243.19 | `results/bench_results.json` |
| `wide-unique` repeat128 proc RSS (MiB) | pr1 | `d4cac03c9` | 5 | 251.01 | 250.05–251.70 | `results/bench_results.json` |
| `wide-unique` repeat128 proc RSS (MiB) | killer | `64b5fb318` | 5 | 225.42 | 224.62–228.34 | `results/bench_results.json` |
| `wide-repeated` scan wall (ms) | base | `cb8c25692` | 7 | 370.93 | 364.05–379.93 | `results/bench_results.json` |
| `wide-repeated` scan wall (ms) | pr1 | `d4cac03c9` | 7 | 116.67 | 100.76–155.10 | `results/bench_results.json` |
| `wide-repeated` scan wall (ms) | killer | `64b5fb318` | 7 | 61.66 | 50.39–64.21 | `results/bench_results.json` |
| `wide-repeated` scan RSS (MiB) | base | `cb8c25692` | 7 | 2054.77 | 2052.34–2057.93 | `results/bench_results.json` |
| `wide-repeated` scan RSS (MiB) | pr1 | `d4cac03c9` | 7 | 2547.39 | 2363.27–2675.20 | `results/bench_results.json` |
| `wide-repeated` scan RSS (MiB) | killer | `64b5fb318` | 7 | 1577.33 | 1316.31–1600.07 | `results/bench_results.json` |
| `wide-repeated` cold take(128) wall (ms) | base | `cb8c25692` | 5 | 32.82 | 32.56–33.60 | `results/bench_results.json` |
| `wide-repeated` cold take(128) wall (ms) | pr1 | `d4cac03c9` | 5 | 45.09 | 43.83–47.23 | `results/bench_results.json` |
| `wide-repeated` cold take(128) wall (ms) | killer | `64b5fb318` | 5 | 21.43 | 16.37–22.47 | `results/bench_results.json` |
| `wide-repeated` cold take(128) RSS (MiB) | base | `cb8c25692` | 5 | 210.57 | 208.87–212.16 | `results/bench_results.json` |
| `wide-repeated` cold take(128) RSS (MiB) | pr1 | `d4cac03c9` | 5 | 236.31 | 235.10–236.63 | `results/bench_results.json` |
| `wide-repeated` cold take(128) RSS (MiB) | killer | `64b5fb318` | 5 | 216.92 | 216.78–218.70 | `results/bench_results.json` |
| `wide-repeated` repeat128 calls 3–10 (ms) | base | `cb8c25692` | 5 | 21.44 | 21.36–21.51 | `results/bench_results.json` |
| `wide-repeated` repeat128 calls 3–10 (ms) | pr1 | `d4cac03c9` | 5 | 3.46 | 3.38–3.60 | `results/bench_results.json` |
| `wide-repeated` repeat128 calls 3–10 (ms) | killer | `64b5fb318` | 5 | 2.56 | 2.54–2.62 | `results/bench_results.json` |
| `wide-clustered` scan wall (ms) | base | `cb8c25692` | 7 | 761.30 | 747.37–826.49 | `results/bench_results.json` |
| `wide-clustered` scan wall (ms) | pr1 | `d4cac03c9` | 7 | 265.21 | 240.60–284.67 | `results/bench_results.json` |
| `wide-clustered` scan wall (ms) | killer | `64b5fb318` | 7 | 111.72 | 101.00–126.31 | `results/bench_results.json` |
| `wide-clustered` scan RSS (MiB) | base | `cb8c25692` | 7 | 5981.67 | 5758.61–5988.34 | `results/bench_results.json` |
| `wide-clustered` scan RSS (MiB) | pr1 | `d4cac03c9` | 7 | 6539.37 | 6050.96–6970.88 | `results/bench_results.json` |
| `wide-clustered` scan RSS (MiB) | killer | `64b5fb318` | 7 | 4517.16 | 4245.21–4520.73 | `results/bench_results.json` |
| `wide-clustered` cold take(128) wall (ms) | base | `cb8c25692` | 5 | 32.57 | 32.35–33.26 | `results/bench_results.json` |
| `wide-clustered` cold take(128) wall (ms) | pr1 | `d4cac03c9` | 5 | 37.99 | 36.88–38.92 | `results/bench_results.json` |
| `wide-clustered` cold take(128) wall (ms) | killer | `64b5fb318` | 5 | 15.69 | 15.65–18.27 | `results/bench_results.json` |
| `wide-clustered` cold take(128) RSS (MiB) | base | `cb8c25692` | 5 | 210.66 | 210.34–212.28 | `results/bench_results.json` |
| `wide-clustered` cold take(128) RSS (MiB) | pr1 | `d4cac03c9` | 5 | 238.08 | 236.40–238.41 | `results/bench_results.json` |
| `wide-clustered` cold take(128) RSS (MiB) | killer | `64b5fb318` | 5 | 218.09 | 217.39–219.83 | `results/bench_results.json` |
| `wide-clustered` repeat128 calls 3–10 (ms) | base | `cb8c25692` | 5 | 21.38 | 21.36–21.43 | `results/bench_results.json` |
| `wide-clustered` repeat128 calls 3–10 (ms) | pr1 | `d4cac03c9` | 5 | 3.93 | 3.37–4.09 | `results/bench_results.json` |
| `wide-clustered` repeat128 calls 3–10 (ms) | killer | `64b5fb318` | 5 | 1.98 | 1.93–2.02 | `results/bench_results.json` |
| `wide-unique-8k` scan wall (ms) | base / pr1 / killer | `cb8c25692` / `d4cac03c9` / `64b5fb318` | 5 | 375.45 / 335.09 / 242.83 | 366.30–379.09 / 314.97–342.75 / 221.94–245.80 | `results/bench_results.json` |
| `wide-unique-8k` cold take(128) wall (ms) | base / pr1 / killer | `cb8c25692` / `d4cac03c9` / `64b5fb318` | 5 | 32.98 / 34.52 / 30.18 | 32.69–33.00 / 34.30–35.30 / 29.97–31.06 | `results/bench_results.json` |
| `wide-template` scan wall (ms) | base / pr1 / killer | `cb8c25692` / `d4cac03c9` / `64b5fb318` | 5 | 744.61 / 580.10 / 396.51 | 688.92–775.54 / 559.62–761.89 / 344.23–424.73 | `results/bench_results.json` |
| `wide-template` cold take(128) wall (ms) | base / pr1 / killer | `cb8c25692` / `d4cac03c9` / `64b5fb318` | 5 | 32.89 / 34.93 / 30.73 | 32.47–33.37 / 34.65–35.28 / 30.44–31.86 | `results/bench_results.json` |
| `wide-mixed` scan wall (ms) | base / pr1 / killer | `cb8c25692` / `d4cac03c9` / `64b5fb318` | 5 | 762.07 / 594.18 / 340.58 | 743.49–801.26 / 566.44–715.77 / 310.75–363.37 | `results/bench_results.json` |
| `wide-mixed` cold take(128) wall (ms) | base / pr1 / killer | `cb8c25692` / `d4cac03c9` / `64b5fb318` | 5 | 31.45 / 34.37 / 29.67 | 30.73–32.28 / 34.17–34.94 / 29.11–30.05 | `results/bench_results.json` |

## Deviations from the handoff

- Root filesystem `/` on `lance-ecs` had 0 B available; all prototype source, Cargo target, temporary caches, and venv files were placed on `/tmp/killer-proto/` (`tmpfs`).
- Benchmark cohort ran a single interleaved pass (`N=7` for `wide-unique`/`wide-repeated`/`wide-clustered` scan, `N=5` for take/repeat and remaining scan cases) rather than dual `primary` + `repeat` cohorts.

## Anomalies (observed, not explained)

- `wide-unique` scan RSS median: `pr1` 4681.52 MiB, `killer` 5777.78 MiB, `base` 5861.23 MiB.
- `wide-template` scan RSS median: `pr1` 4946.45 MiB, `base` 5812.02 MiB, `killer` 5951.26 MiB.

## Not done

- Pure PR branch (`feat/10526-...` or `fix/10526-...`) not extracted yet (review-only stage).
- `narrow`, `wide-low-card`, and `wide-constant` timing benchmarks not re-run (only IPC byte-exact verification ran for `wide-low-card` and `wide-constant`).
- Full workspace `cargo test --workspace` and Python `pytest` suite not run.

## Files

| Path | Purpose |
| --- | --- |
| `review/issue-10526/README.md` | Execution record |
| `review/issue-10526/handoff.md` | Verbatim user request |
| `review/issue-10526/results/bench_results.json` | Raw benchmark medians and min–max ranges |
| `review/issue-10526/results/run_bench.py` | Benchmark runner script used on `lance-ecs` |
| `review/issue-10526/results/environment.txt` | Machine, toolchain, `.so` SHA-256s, dataset sizes |
| `review/issue-10526/results/rust-checks.txt` | Rust fmt/clippy/test counts and IPC round-trip check summary |
