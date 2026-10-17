#!/usr/bin/env bash
# Build both comparison trees with identical profile/flags into separate target dirs and venvs.
set -euo pipefail
source /mnt/lance/env.sh
source /mnt/lance/proxy.sh
proxy-on
B=/mnt/lance/bench-9617
for v in upstream pr; do
  export CARGO_TARGET_DIR=/mnt/lance/target-$v
  if [ ! -d "$CARGO_TARGET_DIR" ]; then
    echo "[$(date +%T)] seeding $CARGO_TARGET_DIR"
    cp -a /mnt/lance/target "$CARGO_TARGET_DIR"
  fi
  cd $B/src-$v/python
  echo "[$(date +%T)] building $v at $(git rev-parse HEAD)"
  /usr/bin/time -v uv sync --frozen --config-settings-package "pylance:build-args=--profile release-with-debug --locked" > $B/logs/build-$v.log 2>&1
  uv run --no-sync python -c "import lance,pyarrow; print(lance.__version__, lance.__file__, pyarrow.__version__)"
  ln -sfn $B/src-$v/python/.venv $B/venv-$v
  echo "[$(date +%T)] done $v"
done
