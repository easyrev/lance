# Candidate C execution record

Result directory: `/mnt/lance/validation-9505/results/20261018T092212Z-C-r1`.
The user authorized implementation, local tests, builds, fixtures, and the finite benchmark matrix.
Do not create a PR or publish upstream comments.

Load the environment in each shell:

```sh
source /mnt/lance/env.sh
source /mnt/lance/proxy.sh
proxy-on
```

U/B/C/P use `/mnt/lance/checkouts/<variant>` and independent `/mnt/lance/targets/<variant>` directories.
P results use `P_reconstructed`. Equivalence with historical P remains unverified.
This run copied the verified U target into new B and C targets with `cp -a --reflink=auto`.
These copies share no writable hard links with U.

The B and C first Python operations used the repository install entrypoint:

```sh
export CARGO_TARGET_DIR=/mnt/lance/targets/C
cd /mnt/lance/checkouts/C/python
make install UV_SYNC='uv sync --frozen --config-settings-package "pylance:build-args=--profile release-with-debug --locked"'
```

The first C install failed on new-code integration errors. Preserve `logs/C-initial-install.log`.
The second install uses the same command. It corrects visibility, pool wrapper types, and physical-expression downcasts.
No benchmark ran during these builds.

The coordinator creates one child cgroup per worker under `/sys/fs/cgroup/lance9505-validation`.
The coordinator stays outside this group. Each child has explicit memory and swap limits.
`logs/direct-cgroup-preflight.log` records the 2 GiB and zero-swap controls.
The first systemd preflight used an incorrect path. Its failed reads remain in `logs/cgroup-preflight.log`.
The corrected systemd preflight also confirms the memory controls.

Invoke the external harness through an initialized checkout:

```sh
cd /mnt/lance/checkouts/U/python
uv run --no-sync python /mnt/lance/validation-9505/results/20261018T092212Z-C-r1/bench.py generate tiny
```

The harness refuses measurements while Cargo or rustc runs. It refuses to overwrite run directories.
Warm reads use only the initial fixture's referenced data files.
Validation runs in a separate 8 GiB cgroup after execute metrics and resource events are saved.
Validation checks every field against a deterministic row oracle.
Source epoch 1 differs from target epoch 0 in every non-key field of the full-schema reverse workload.

Current stage: implementation and build. Gate 1 and all measurement gates remain pending.
Next: finish builds, run regression and mechanism tests, correct defects, and obtain the required read-only review.
Freeze source and binaries before formal measurements.
