> Historical report. Status statements describe the stage when this report was written. See the [review index](../README.md) for the published branch context. Only links were adapted below. The [original report](../evidence/python-contract-review.md) remains byte-identical.

# Python contract review and fixes

This was a focused implementation self-review, not the separate independent
review required for the complete candidate. It used the current candidate diff,
baseline source contracts, and added tests. No Phase 1 material was read.

## Confirmed findings

1. Lazy Hugging Face registration replaced existing registrations for sibling
   Hugging Face classes. Registering an `IterableDataset` adapter first did not
   protect it when a later `Dataset` input initialized the built-in adapters.
   The fix registers only the type of the input that reached the fallback.
2. Streaming scanner adapters added dependencies on `projected_schema` and the
   private Lance `_snapshot` attribute. Previously, scanner subclasses needed
   only a working `to_reader()` method. The fix preserves that contract for
   opaque scanner subclasses. Exact eligible Lance scanners retain the factory
   path. Other Lance scanners use their existing reader directly.
3. The zero-retry test expected the word `conflict`, but the measured public
   error was `Too many concurrent writers. Attempted 0 retries.` The test now
   matches that specific error. Evidence: the baseline zero-retry calibration
   result in `calibration-small/baseline-release-lance-conflict-zero-retry/result.json`.

The tests cover registration order and both Arrow and Lance scanner subclasses.
Each scanner subclass supplies `to_reader()` and rejects `projected_schema`
access. The test also writes the scanner through the normal dataset write API.

## Verification

All commands ran from `/workspace/lance-7895/python`, after sourcing `env.sh`.
They used `uv run --no-sync` and the baseline native extension with candidate
Python files. These tests do not require the new native replay provider.

- Focused regressions: `pytest -q python/tests/test_dataset.py -k
  'lazy_source_registration_preserves_custom_adapter or
  custom_scanner_source_only_requires_to_reader'`: 3 passed.
- Related source contracts: `pytest -q python/tests/test_dataset.py -k
  'source_preserves_unsafe_scan_options or
  filtered_arrow_dataset_source_preserves_filter or
  source_pins_lance_version_and_schema or
  replayable_lance_scan_preserves_projection_and_order or
  lazy_source_registration_preserves_custom_adapter or
  custom_scanner_source_only_requires_to_reader'`: 10 passed.
- `ruff format --check` and `ruff check` passed for `types.py`, `dataset.py`,
  and `test_dataset.py`. `git diff --check` passed.

The first regression run had 2 passes and one fixture failure: the Hugging Face
generator constructor tried to create a cache in a read-only directory. The
fixture now calls `Dataset.to_iterable_dataset()`, which needs no disk cache.
This was a test setup failure, not a source adapter failure.

Receipts: `python-review-regressions.log` (initial),
`python-review-regressions-final.log`, `python-review-contracts-final.log`,
`python-review-ruff.log`, `python-review-runtime.txt`, and
`python-review-sources.sha256`. The runtime receipt records Python 3.12.14,
PyArrow 25.0.1, the candidate package path, and the native extension SHA-256.

Remaining useful verification includes real retry preservation of `FirstSeen`
duplicate-key winners and actual volatile values on the buffered fallback.
Current tests assert row order and fallback classification separately. These
end-to-end cases require the completed native candidate build.
