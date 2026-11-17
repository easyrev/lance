> Historical run, kept as recorded. Prepared 2026-11-16 against the baseline
> `d8293547c` and the then-tip `ab6f31589`. The fix-branch figures below do not
> validate any later commit; `repro-794031b87.log` covers the current tip.

# #7207 reproduction: raw output

Harness: `rust/lance/src/io/commit/repro_7207.rs`, registered in `io/commit.rs`
as `#[cfg(test)] mod repro_7207;`. This harness is not part of the fix branch.

Setup: 200 rows across 20 fragments, one BTree index on `i`. Twenty rounds of
"plan and execute compaction, then inject a DELETE that conflicts with the
Rewrite commit so it fails". Measured: `_indices/{uuid}` directories not
referenced by the latest manifest, and their total bytes.

Command:

```bash
cargo test -p lance --lib repro_7207 -- --nocapture
```

## base commit d8293547c

```text
running 1 test
ORPHANS after 20 failed compaction commits: dirs=20 bytes=72760
test io::commit::repro_7207::repro_7207_leaked_index_dirs ... ok

test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 10873 filtered out; finished in 1.11s
```

## fix branch `fix/7207-failed-commit-index-cleanup` (ab6f31589)

The same harness was applied on top of the fix branch (not committed there):

```text
running 1 test
ORPHANS after 20 failed compaction commits: dirs=0 bytes=0
test io::commit::repro_7207::repro_7207_leaked_index_dirs ... ok

test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 10884 filtered out; finished in 0.89s
```
