# Verification on d0020f429

| Check | Exit | Outcome |
| --- | ---: | --- |
| `cargo fmt --all` and post-amend `cargo fmt --all -- --check` | 0 | Formatting passed. |
| `cargo test -q -p lance-encoding -p lance-file --profile release-no-lto` | 0 | lance-encoding 2,648 passed, 3 ignored. lance-file 479 passed. Doctests 16 passed, 1 ignored. |
| Isolated one-batch benchmark | 0 | Each revision passed its warmup and three measured trials, with full scan and random take readback. |
| `rtk cargo clippy --all --tests --benches -- -D warnings` | 101 | Apple Silicon reports unreachable expressions in the Arm64 byte-stream-split implementation at lines 358 and 393. Both lines are identical to upstream. |
| `make install` | 2 → 0 | First attempt encountered crates.io HTTP/2 errors. The same command succeeded with Cargo HTTP multiplexing disabled. |
| `make build` | 0 | Rebuilt and installed the editable native extension from this checkout. |
| `uv run pytest python/tests/test_file.py` | 0 | 48 passed on Python 3.13.13. |
| `uv run make lint` | 0 | Ruff, Pyright, Python-crate Rust format and Clippy completed. Pyright reported 0 errors and 18 warnings. |

The original review fixture inferred a buffer of 32-bit integers. The final test uses byte-typed payloads, and the complete suite passed after that correction. The original full-suite failure is retained as `rust-tests-fixture-failure.log`.

[Exact Rust suite log](rust-tests.log) · [Strict clippy output](rust-clippy-raw.log) · [Benchmark results](benchmark-results.md)

[Python file suite](python-test-file.log) · [Native module path](python-native-path.txt) · [Python lint](python-lint.log)
