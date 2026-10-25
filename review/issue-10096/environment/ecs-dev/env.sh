# Source from a synchronized checkout while holding its worktree lock.
# LANCE_WORKTREE must be the same name passed to sync.py.
: "${LANCE_WORKTREE:?Set LANCE_WORKTREE}"
[[ $LANCE_WORKTREE =~ ^[a-zA-Z0-9_-]+$ ]] || return 1
[[ -s /mnt/lance/volume.uuid ]] || { echo "Missing volume identity" >&2; return 1; }
[[ $(findmnt -rn -M /mnt/lance -o UUID) = "$(cat /mnt/lance/volume.uuid)" ]] || { echo 'Expected data volume is not mounted' >&2; return 1; }
export LANCE_CHECKOUT=/mnt/lance/checkouts/$LANCE_WORKTREE
[[ -f /mnt/lance/state/$LANCE_WORKTREE/verified ]] || { echo 'Source is not verified; resync first' >&2; return 1; }
# Maturin can invoke the compiler wrapper outside Cargo. Pin rustup explicitly
# so sccache does not probe its fallback `stable` toolchain.
export RUSTUP_TOOLCHAIN=$(sed -n 's/^channel = "\([^"]*\)"/\1/p' "$LANCE_CHECKOUT/rust-toolchain.toml")
[[ -n $RUSTUP_TOOLCHAIN ]] || { echo 'Missing repository Rust toolchain pin' >&2; return 1; }
export CARGO_HOME=/mnt/lance/cache/cargo
export UV_CACHE_DIR=/mnt/lance/cache/uv
export SCCACHE_DIR=/mnt/lance/cache/sccache
export SCCACHE_CACHE_SIZE=40G
export CARGO_TARGET_DIR=/mnt/lance/targets/$LANCE_WORKTREE
export TMPDIR=/mnt/lance/tmp
export PATH="$CARGO_HOME/bin:$HOME/.local/bin:$PATH"
export RUSTC_WRAPPER=sccache CARGO_INCREMENTAL=0
# sccache reads this when its server starts. Restart it under the exclusive
# host lock after adding checkout roots, before starting any compiler clients.
printf -v SCCACHE_BASEDIRS '%s:' /mnt/lance/checkouts/*
export SCCACHE_BASEDIRS=${SCCACHE_BASEDIRS%:}
export UV_PROJECT_ENVIRONMENT="$LANCE_CHECKOUT/python/.venv"
export CC=clang CXX=clang++
mkdir -p "$CARGO_TARGET_DIR"
cd "$LANCE_CHECKOUT"
