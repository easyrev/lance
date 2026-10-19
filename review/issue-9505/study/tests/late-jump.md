# Late payload small-to-large supplemental test

`late-jump.patch` is a test-only patch against the identical `condition.rs` in D `50e216972e1558ce253bece5db462d8241fde96a` and the frozen DB port. It does not modify the frozen ports or candidate production code.

## Fixture and asserted mechanism

The test calls `MergeConditionExec::execute(0, ...)` directly over one `TestMemoryExec` partition. It therefore controls the order of addresses actually submitted to the materializer; no hash join can reorder them.

One small 1-byte Utf8 value and ten 64-KiB Utf8 values occupy two separate fragments. This prevents the initial small Take from retaining an allocation that also contains the large values. The ordered input repeats `small, large × 10` for either one or three groups. Repeated groups reuse the same stored addresses: this isolates materializer behavior, rather than claiming a duplicate-key merge is valid.

The finite pool is 1 MiB, the partition count is one, and `batch_size` is eight. The implementation therefore derives a 128-KiB soft byte target. Each group asserts these observations:

| Output chunk | Rows | Arrow-byte assertion |
| --- | ---: | --- |
| Initial small value | 1 | Its actual Take bytes allow the next eight-row chunk |
| First consecutive large chunk | 8 | Output Arrow bytes are at least 512 KiB, at least 4 times the soft target |
| Remaining large value | 1 | Output Arrow bytes fall below the soft target |
| Remaining large value | 1 | Output Arrow bytes fall below the soft target |

The test records `(output_rows, output_arrow_bytes, delta_payload_take_arrow_bytes)` in an observations vector and includes it in assertion diagnostics. It also checks every input column, payload value, row order and total taken-row metric. Thus a passing result demonstrates that width feedback changes the next chunk after the oversized chunk has already been materialized. It does not establish a peak RSS bound, a Take allocation bound, or the behavior of a reordered end-to-end merge.

## Running the test

Apply the patch to a separate D or DB test snapshot, then run:

```sh
cargo test -p lance --profile release-with-debug --lib payload_soft_sizing_reacts_after_consecutive_large_values
```

This selects two rstest cases. No overlay feature flag is required. The fixture stores eleven rows, roughly 640 KiB of logical payload; the three-group case changes only the ordered input addresses.

## Validation status

The patch passes `git apply --check` against a temporary copy of DB `condition.rs`; applying it reproduces the formatted test source byte for byte. The temporary source was formatted with rustfmt. No build, test, Clippy, SSH operation or production edit ran while preparing this artifact. The numerical assertions are proposed execution gates, not observed results yet.
