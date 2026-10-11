> Historical report. Status statements describe the stage when this report was written. See the [review index](../README.md) for the published branch context. Only links were adapted below. The [original report](../evidence/README.md) remains byte-identical.

# Issue 7895 measurement support

These scripts compare fixed upstream and candidate snapshots. They do not establish a performance result until both matched builds finish.

Use `release-with-debug` for both snapshots. Keep Python, PyArrow, compiler options, thread limits, and fixture files equal. Finish builds before timing.

The snapshots must contain the complete `lance` package and its extension. Do not use the active worktree as a benchmark snapshot.

## Commands

Run these commands from `/workspace/lance-7895/python`. The commands use the existing `uv` environment.

```bash
source /workspace/issue-7895-evidence/env.sh
evidence=/workspace/issue-7895-evidence
baseline_package="$evidence/baseline-perf-python"
candidate_package="$evidence/candidate-perf-python"

# Run detector controls before the final measurements.
uv run --no-sync python "$evidence/detector-controls.py" \
  --baseline "$baseline_package" --candidate "$candidate_package" \
  --fixture "$evidence/calibration-small" --run-id final

# Capture each plan once. Existing output directories deliberately cause failure.
for fixture in benchmark-fixture-small benchmark-fixture; do
  for label in baseline candidate; do
    package="$candidate_package"
    if [[ "$label" == baseline ]]; then package="$baseline_package"; fi
    "$evidence/capture-plans.sh" --package "$package" --label "$label" \
      --root "$evidence/$fixture" --output "$evidence/plans"
  done
done

# Start only after both builds finish and the machine becomes idle.
for fixture in benchmark-fixture-small benchmark-fixture; do
  "$evidence/run-matrix.sh" "$baseline_package" "$candidate_package" \
    "$evidence/$fixture" 5
  uv run --no-sync python "$evidence/summarize.py" \
    "$evidence/$fixture" --repetitions 5 > "$evidence/$fixture-summary.json"
done

uv run --no-sync python "$evidence/write-performance-report.py" \
  --base 4ac2f7c88be1ea2ab2c0fbb61d02238883fc18b9 \
  --candidate 26632629ca162cdbfd82dabad1d80e3e6c92b364
```

Baseline plans may already exist. In that case, capture only candidate plans. Keep completed plan files and their binary hashes.

Use `--run-id dev` for preliminary detector controls. Development binaries can verify the mechanism, but their elapsed times are not final performance evidence.

## Checks and retained evidence

- The small fixture contains 8,192 rows and 128-byte payloads. The large fixture contains 262,144 rows and 512-byte payloads.
- The target starts with one matching row. The merge updates that row and inserts the remaining source keys.
- Each trial starts in a fresh Python process. It reads source files before timing to establish a warm filesystem cache.
- Timing covers merge execution and the concurrent update when enabled. Fixture copies, cache warming, plan capture, and correctness checks remain outside timing.
- Each merge enables three conflict retries. Conflict trials commit an overlapping update through a separate thread before the first merge commit.
- Conflict trials require exactly two commit hooks, for versions 2 and 3. Every successful trial must report one update and the expected inserts.
- Each hook records entry and release times. The first hook precedes the concurrent update and randomized retry wait.
- The merge must produce the expected versions, unique keys, values, and complete payload checksum. Zero-retry controls must fail with write contention.
- The matrix alternates baseline and candidate order between repetitions. It preserves every observation, including slow runs.
- Each result records extension, Python source, and probe hashes. The summary rejects incomplete matrices, mixed hashes, different environments, and failed correctness checks.
- Temporary targets are removed after validation. Raw results, plans, and probe logs remain under this directory.

## Detector scope

The external `LD_PRELOAD` library observes temporary-directory creation before replay starts. This catches replay that stays entirely in memory.

Controls require replay for small one-shot inputs and no replay for materialized tables. Candidate LanceDataset and Arrow Dataset controls require no replay.

Opaque PyArrow Scanner controls require replay. This fallback preserves scanner behavior when public APIs cannot establish repeatability.

The probe also records `spill.arrows` size before removal. This size measures the completed temporary file, not physical storage traffic.

Directory names alone are insufficient attribution. Keep the positive-control call stack, resolved symbols, and the corresponding `spilling_table_provider` source call.

Replay also causes extra probe log writes. Very small elapsed-time differences can include this observation overhead. The fallback cases help assess ordinary variation.

## Interpretation limits

`max_rss_kib` is the process high-water mark at merge completion. It includes imports and setup. It is not isolated replay memory.

Conflict wall time includes random backoff. The first failure selects 0–3 slots, each approximately 1.1 times the first attempt duration.

Paired trials do not share a random slot. Compare first-hook duration and process CPU alongside wall time. Do not subtract an estimated wait.

CPU totals include user and system time for both attempts and the concurrent update. Hook timestamps cannot isolate the exact backoff interval.

`/proc/self/io` includes source reads, target writes, and probe logging. Report logical bytes separately from kernel-accounted writes and cancelled writes.

`analyze_plan` executes the actual source without committing. Its normalized output removes timing metrics and paths while preserving operators and join configuration.

Compare raw plans as well as normalized plans. Normalization does not expose every optimizer estimate and does not prove identical provider statistics.

Check source operators, join direction, partitioning, input batch counts, and output counts. Explain any difference before attributing elapsed-time changes to replay.

Treat raw Scanner as a fallback comparison. Do not describe it as an optimized input or combine its results with eligible source types.

These measurements cover local warm-cache workloads. They do not establish cold-cache, remote-storage, or cloud performance.

## Rebuild and fixture provenance

`performance-build-provenance.json` records the fixed commits, Rust version, Cargo configuration hashes, build directory, interpreter, and profile. Build each snapshot at its recorded commit with:

```bash
source /workspace/issue-7895-evidence/env.sh
export PYO3_PYTHON=/workspace/lance-7895/python/.venv/bin/python
unset PYO3_ENVIRONMENT_SIGNATURE
cargo build --locked --profile release-with-debug --manifest-path python/Cargo.toml
```

Run `make install` from the repository's `python/` directory before Python commands in a fresh worktree. The saved setup and build logs record this environment's initial installation. Both performance snapshots use the same scoped linker wrapper to compress DWARF sections. `snapshot-performance.sh` preserves the full debug artifact, removes debug sections from execution copies, and verifies every loadable ELF section. The different build-job limits affect build scheduling; no LTO or optimization setting was changed.

`baseline-python-source-verification.json` compares every tracked baseline Python package file with the official base. The native hashes and ELF checks bind each measurement to its saved build.

To regenerate fixtures, use new, empty output paths and point the measurement scripts at them. The generator uses seed 7895 and writes both Lance and Parquet from the same Arrow table:

```bash
uv run --no-sync python "$evidence/benchmark.py" --package "$baseline_package" \
  --root /tmp/issue-7895-small --prepare --rows 8192 --width 128
uv run --no-sync python "$evidence/benchmark.py" --package "$baseline_package" \
  --root /tmp/issue-7895-large --prepare --rows 262144 --width 512
uv run --no-sync python "$evidence/benchmark.py" --package "$baseline_package" \
  --root /tmp/issue-7895-control --prepare --rows 8 --width 16
```

The retained fixture JSON files record row count, payload width, Arrow byte count, fragment count, seed, versions, and payload checksum. They are validated again in every trial. The external probe can be rebuilt from `replay_probe.c` with `cc -shared -fPIC -O2 -o replay_probe.so replay_probe.c -ldl`; record the resulting hash before new measurements.
