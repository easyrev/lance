#!/usr/bin/env bash
set -euo pipefail
variant="$1"
run_root=/mnt/lance/unified-9505-20261019
checkout="/mnt/lance/checkouts/unified-9505-${variant}"
target="/mnt/lance/targets/unified-9505-${variant}"
mkdir -p "$run_root/logs"
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/${variant}-build-exit-code"' EXIT
source /mnt/lance/env.sh
source /mnt/lance/proxy.sh
proxy-on >/dev/null
export CARGO_TARGET_DIR="$target"
export CARGO_BUILD_JOBS=6
export MATURIN_PEP517_ARGS="--profile release-with-debug --locked --interpreter $checkout/python/.venv/bin/python"
date -u --iso-8601=seconds
git -C /mnt/lance/src/lance worktree add --detach "$checkout" 0a0d327082988018a25f56147d3b6d02f6c79ecc
git -C "$checkout" apply --check "$run_root/ports/$variant/implementation.patch"
git -C "$checkout" apply "$run_root/ports/$variant/implementation.patch"
git -C "$checkout" diff --binary > "$run_root/logs/${variant}-applied.patch"
cp -a --reflink=auto /mnt/lance/targets/U_main "$target"
cd "$checkout/python"
make install > "$run_root/logs/${variant}-install.log" 2>&1
make -f Makefile -f /mnt/lance/validation-9505/review/issue-9505/harness/profile.mk build UV_RUN="uv run --no-sync" > "$run_root/logs/${variant}-build.log" 2>&1
uv run --no-sync python -c 'import hashlib, json, platform, sys, lance, lance.lance, pyarrow; from pathlib import Path; p=Path(lance.lance.__file__); print(json.dumps(dict(python=sys.version, platform=platform.platform(), lance=lance.__version__, pyarrow=pyarrow.__version__, extension=str(p), extension_sha256=hashlib.sha256(p.read_bytes()).hexdigest()), indent=2))' > "$run_root/logs/${variant}-binary.json"
uv pip freeze > "$run_root/logs/${variant}-dependencies.txt"
sha256sum "$checkout/Cargo.lock" "$checkout/python/Cargo.lock" "$checkout/python/uv.lock" "$checkout/.cargo/config.toml" "$checkout/python/.cargo/config.toml" > "$run_root/logs/${variant}-build-inputs.sha256"
rustc -Vv > "$run_root/logs/${variant}-rustc.txt"
date -u --iso-8601=seconds
