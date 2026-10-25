# Minimal Lance ECS environment

Use native SSH, Git, rsync, flock and tmux. `sync.py` is the only synchronization
helper. There is no scheduler or test runner. Existing source and network
configuration are preserved. Remote worktrees have independent Git metadata,
virtual environments and targets; only download/compiler caches are shared.

## First setup

The existing `lance-ecs` SSH alias must select the intended host. Inspect
`ssh lance-ecs 'hostname; lsblk -o NAME,SERIAL,SIZE,FSTYPE,MOUNTPOINTS'` first.
Deploy these files into a temporary directory together with the **current
checkout's** `rust-toolchain.toml` (the supplied copy records this delivery's pin):

```sh
ssh lance-ecs 'mkdir -p /tmp/lance-ecs-setup'
rsync -rt output/ecs-dev/{setup.sh,env.sh} rust-toolchain.toml lance-ecs:/tmp/lance-ecs-setup/
# Only for the verified blank 300 GiB disk: this explicitly authorizes formatting.
ssh lance-ecs 'bash /tmp/lance-ecs-setup/setup.sh --initialize uf6b150xov6p41lzez5z'
# Subsequent runs never format:
ssh lance-ecs 'bash /tmp/lance-ecs-setup/setup.sh'
```

Setup checks the serial, exact size, partitions, holders, signatures and mounts.
Only the blank expected disk can be initialized. It mounts ext4 by UUID using
`/etc/fstab`, keeping a backup before the first edit. Unexpected existing
filesystems or mount definitions cause failure. Ubuntu 24.04 x86_64 is required.
Setup takes the exclusive host lock during tool installation.
It installs the repository Rust pin with its components, uv and sccache 0.19.0
(the official release checksum is verified). Re-run with the updated pin when
the repository changes its toolchain. The environment exports the repository toolchain pin explicitly for maturin and
sccache compiler probes. No CPU flags or Cargo profiles are changed.

## Synchronize

From a local Git checkout, including one with unpublished commits:

```sh
python3 output/ecs-dev/sync.py dev
# Or select a disposable/independent local worktree:
python3 output/ecs-dev/sync.py experiment --source /path/to/worktree
```

The helper uses `git ls-files --cached --others --exclude-standard -z`. It copies
regular files, executable modes and symlinks into a temporary snapshot. Tracked
working deletions are omitted. Generated native libraries, Python caches,
virtual environments, targets, and root `output/`, `results/`, `cache/`, `caches/`
are excluded even if tracked. This means files under this delivery's `output/`
are deployed separately. Git LFS pointers and submodules are not materialized;
submodules are rejected rather than silently copied incompletely. Do not edit the
local source while snapshotting. Remote source edits must use the worktree lock.

For a partial local Git clone, seed the remote bare repository once from a
published base before pushing; otherwise Git may lazily download historical blobs
locally to construct the initial push. After the first helper attempt creates the
bare repository, use ordinary Git under the worktree lock, for example:

```sh
ssh lance-ecs 'flock -x /mnt/lance/locks/worktree-dev.lock git -C /mnt/lance/git/dev.git fetch --depth=1 https://github.com/easyrev/lance.git PUBLISHED_SHA:refs/heads/source'
```

Then retry synchronization. Replace `PUBLISHED_SHA` with an actual published
ancestor of local HEAD. The helper permits shallow fetches into the independent
checkout; subsequent unpublished commits still travel by SSH push.

Git commits travel via native `git push` over SSH into `/mnt/lance/git/NAME.git`.
The helper updates only its private `source` ref, including branch switches.
The independent checkout's index and HEAD identify that commit.
The helper then overlays the working files. Local staging status stays local. Deletion is restricted to the previous managed path
list; unknown collisions fail. No recursive deletion or rsync `--delete` is used.
Checksum dry-run differences fail verification. The helper retains the revision,
binary working diff, managed paths and verification record in
`/mnt/lance/state/NAME/`. Interrupted syncs are recoverable by resyncing. Stop using
the checkout until resync succeeds. Untracked file contents are present in the
checkout; capture them with the source archive for benchmark provenance.

## Run ordinary commands

All cooperating operations must take locks in this order: **worktree first,
host second**, then source the environment. Synchronization takes only the
worktree lock. Use a new shell/subshell per command so locks are released on exit.
Sourcing `env.sh` checks the mount and verification gate. Locks are advisory:
manual commands which bypass them are not protected.

```sh
ssh lance-ecs 'bash -s' <<'REMOTE'
set -euo pipefail
export LANCE_WORKTREE=dev
exec 9>/mnt/lance/locks/worktree-$LANCE_WORKTREE.lock
flock -x 9
exec 8>/mnt/lance/locks/heavy.lock
flock -s 8
source /mnt/lance/tools/env.sh
cargo test --locked -p lance-core test_row_address
REMOTE
```

For Python, run `make install` from `python/` first in **each new checkout**.
Let it finish. Only repeat dependency sync when `pyproject.toml`/`uv.lock` changes.
Within the locked shell above:

```sh
cd python
make install UV_SYNC='uv sync --frozen --config-settings-package "pylance:build-args=--profile dev"'
# Before every test session, including unchanged source:
make build
uv run --frozen --no-sync pytest python/tests/test_dataset.py::test_dataset_overwrite
```

The install command uses the existing `dev` profile to match `make build`.
`make build` asks Cargo to check native inputs, including Rust binding changes.
Tests use the locally built editable extension in this worktree's `python/.venv`.
Never copy a venv or target between worktrees. Shared caches live in
`/mnt/lance/cache/{cargo,uv,sccache}`; `TMPDIR` uses `/mnt/lance/tmp`.
`CARGO_INCREMENTAL=0` enables sccache. `SCCACHE_BASEDIRS` normalizes C/C++ cache paths.
Sccache 0.19 retains the working directory in Rust cache keys. Independent
worktrees therefore do not currently share Rust cache hits. Each worktree still
reuses its own Cargo target. Link steps and procedural macros cannot be cached.
After adding worktrees, stop the existing sccache server once with
`sccache --stop-server` while holding the exclusive host lock, then start it
from the updated environment with `sccache --start-server`. Its path list is
loaded at server startup.
See [sccache Rust limitations](https://github.com/mozilla/sccache/blob/v0.19.0/docs/Rust.md)
and [path configuration](https://github.com/mozilla/sccache/blob/v0.19.0/docs/Configuration.md).

## Long commands and measurements

Start a terminal and retain the shell across SSH disconnections:

```sh
ssh -t lance-ecs 'tmux new-session -A -s lance-dev'
```

Inside tmux, open a subshell and use the same lock/environment commands above.
Use `tee /mnt/lance/results/NAME/build.log` with `set -o pipefail`, inspect failures
in the terminal, and retry ordinary commands. Detach with Ctrl-b d; reconnect with
`ssh -t lance-ecs 'tmux attach -t lance-dev'`. An SSH ControlMaster reuses the
connection, not shell cwd or environment.

For a benchmark take `flock -x 8` instead of `flock -s 8`. Before measurement inspect
`ps -eo pid,ppid,pcpu,pmem,comm,args --sort=-pcpu` for unmanaged cargo, rustc, pytest,
maturin or other heavy jobs. Investigate unexpected jobs; do not kill them.
With both locks held, retain provenance and real Criterion results:

```sh
result=/mnt/lance/results/$LANCE_WORKTREE/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$result"
cp /mnt/lance/state/$LANCE_WORKTREE/{revision,working.diff,verified} "$result/"
git status --short > "$result/status.txt"
# Include untracked source contents as well as the committed revision and diff.
tar --exclude=.git --exclude=.venv --exclude=target --exclude=__pycache__ --exclude=.pytest_cache --exclude='*.so' -czf "$result/source.tar.gz" .
{ rustc -Vv; cargo -V; uv --version; sccache --version; clang --version; uname -a; lscpu; } > "$result/tools.txt"
ps -eo pid,ppid,pcpu,pmem,comm,args --sort=-pcpu > "$result/processes.txt"
printf '%s\n' 'cargo bench --locked -p lance-linalg --profile release-with-debug --bench argmin -- --sample-size 10 --warm-up-time 1 --measurement-time 1' > "$result/command.txt"
cargo bench --locked -p lance-linalg --profile release-with-debug --bench argmin -- --sample-size 10 --warm-up-time 1 --measurement-time 1 2>&1 | tee "$result/output.log"
cp -a "$CARGO_TARGET_DIR/criterion" "$result/criterion"
{ sccache --show-stats; df -h /mnt/lance; du -sh /mnt/lance/cache/* "$CARGO_TARGET_DIR"; } > "$result/cache-disk.txt"
```

The measured command must succeed (`set -euo pipefail`); a compiled binary alone
is not a benchmark result. Retain failures and partial evidence with their actual
status. Use `release-with-debug` for optimized measurements, keeping repository
CPU flags. A warm unchanged rebuild proves Cargo reuse; positive sccache hits
from a second independent target prove cross-worktree compiler reuse. They are
different checks and do not predict changed-code build latency.

## Verification evidence

[VERIFICATION.md](VERIFICATION.md) records the checks completed on the live host.
The `evidence/` directory retains logs and the exact shell commands used.
`test_sync.py` is a live integration regression test. It creates its own disposable
remote checkout and tests corruption recovery, unmanaged-file protection and locks.
Run it with `python3 -m unittest discover -s output/ecs-dev -p test_sync.py -v`.
