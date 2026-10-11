#!/usr/bin/env bash
set -euo pipefail
source /workspace/issue-7895-evidence/env.sh
cd /workspace/lance-7895/python
backup=$(mktemp /workspace/issue-7895-evidence/pyproject-build.XXXXXX)
cp -p pyproject.toml "$backup"
restore() {
  cp -p "$backup" pyproject.toml
  rm -f "$backup"
}
trap restore EXIT
uv run --no-sync python - <<'PY'
from pathlib import Path
path = Path('pyproject.toml')
text = path.read_text()
assert text.count('[tool.maturin]\n') == 1
path.write_text(text.replace('[tool.maturin]\n',
    '[tool.maturin]\nstrip = true\nrustc-args = ["-C", "debuginfo=0"]\n'))
PY
# Maturin applies these options only to the final crate. Reuse dependency code,
# retain the repository's dev profile, and avoid two 3.1GiB debug copies.
CARGO_BUILD_JOBS=2 uv run --frozen --no-sync make build UV_RUN='uv run --frozen --no-sync'
