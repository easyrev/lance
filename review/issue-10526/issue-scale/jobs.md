# Local execution

| Job | Driver | Log | Exit status |
| --- | --- | --- | --- |
| initial Rust suite | exec session 57614 | rust-tests-initial.log | rust-tests-initial.exit |
| verification, sequential | exec session 43132 | verification.log | verification.exit and each stage's .exit |
| benchmark | benchmark stage of verification | benchmark.log, build logs, individual trial logs and memory traces | benchmark.exit, build and trial .exit files |

The initial suite compiled while the follow-up tests were being finished. Its status is kept for provenance. The exact committed suite is the reference for readiness. The first full-suite attempt on the review follow-up found a test fixture whose numeric fill was inferred as i32 rather than u8. Its failure is preserved separately as rust-tests-fixture-failure.log and rust-tests-fixture-failure.exit.

The final benchmark checkout moved from 6be27ca3b to d0020f429 while the baseline executable was being built. The amendment only changes the intended byte type of the fixture. The final executable build started after the amendment. benchmark-shas.txt identifies the two actual source revisions.

The first A/B attempt used a shared Cargo target. The second build compiled only the example and produced the baseline's byte-identical file and page metrics. That attempt is quarantined under shared-target-attempt and excluded from inference. The rerun uses independent baseline and final targets and checks that the baseline writes one page and the final writer splits into 135 pages.

| Job | Driver | Log | Exit status |
| --- | --- | --- | --- |
| isolated A/B and final Rust-suite retry | exec session 92138 | retry.log, benchmark.log, rust-tests.log | retry.exit, benchmark.exit, rust-tests.exit |

The retry starts after the strict Rust Clippy child exits. The verification parent waits until the new A/B and Rust suite finish before starting the Python build. This keeps compilation and measurement sequential.

| Job | Driver | Log | Exit status |
| --- | --- | --- | --- |
| Python network retry | exec session 62023 | python-install-retry.log, python-build.log, python-test-file.log, python-lint.log | matching .exit files |

The first `make install` failed during Cargo metadata when crates.io downloads hit HTTP/2 framing errors. The retry runs the same workflow with `CARGO_HTTP_MULTIPLEXING=false CARGO_HTTP_TIMEOUT=45 CARGO_NET_RETRY=1 CARGO_BUILD_JOBS=4` and the same verification target directory.

The initial wrapper returned the shell status of its last conditional. The per-stage exit files record actual outcomes. The reproduction script now returns a nonzero aggregate status when any stage fails and still attempts independent stages.
