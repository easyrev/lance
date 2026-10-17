Title: fix(merge_insert): preserve statistics for small streamed sources

Non-indexed row rewrites can build the hash table from a large target when a small reader reports no statistics. Buffer a bounded source prefix and use a MemTable only after EOF. Preserve exact statistics after FirstSeen deduplication for small inputs. Larger streams keep their prefix, ordering, and existing retry policy.

Use Lance's bounded execution context for the non-indexed plan. Keep DataFusion's join selection and partitioning optimizations, so large sources can still build from a smaller target. The change does not modify indexed join, scan batching, or write sinks.

Related to #9505. This addresses missing statistics for small readers; it does not provide a process-wide memory cap or resolve inaccurate target-width estimates for very large variable-length values.

Validation: 337 Rust merge_insert tests, 42 Python merge_insert tests, two plan doctests, workspace Clippy, formatting, and full Python lint passed. On a 16-vCPU ECS host, a warm-storage benchmark with 64M target rows, 44 columns, and a 100-row reader reduced median merge latency from 24.24s to 5.96s and peak RSS from 44.04 GiB to 1.24 GiB (two runs). A 4M-row case completed twice under a 2 GiB cgroup where main was OOM-killed twice. The reverse 3M-source/100K-target case also completed with a 1 GiB execution pool.

