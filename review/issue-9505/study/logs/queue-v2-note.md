# Test queue scheduling change

At 2026-10-18 20:54 UTC the original `test-rest.sh`, DP branch of
`test-integration.sh`, and `start-when-ready.sh` were still waiting. Neither DB
nor DP Rust test checkout existed. These three owned waiting wrappers were
stopped before they launched tests or benchmarks; their logs and any EXIT-trap
status are preserved with a `queue-v1` name.

`test-rest-v2.sh` starts the independent DB and DP Rust test builds together
after DB/CTX Python builds finish. The DP test snapshot can be built from its
already frozen patch before the independent DP Python build finishes.
`test-integration-dp-v2.sh` waits for both Rust suites, then uses eight compile
jobs instead of four. Production source, Cargo profiles, test contents and
test-thread settings are unchanged. The original readiness coordinator is
restarted after preserving cancellation artifacts. Every performance cell
still waits for all builds and tests to exit and rejects active compilation.
