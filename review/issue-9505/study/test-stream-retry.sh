#!/usr/bin/env bash
set -euo pipefail
variant="$1"
run_root=/mnt/lance/unified-9505-20261019
case "$variant" in
    D) checkout=/mnt/lance/checkouts/K_check ;;
    DB|DP) checkout="/mnt/lance/checkouts/unified-9505-${variant}" ;;
    *) exit 2 ;;
esac
test ! -e "$run_root/logs/${variant}-stream-retry-exit-code"
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/${variant}-stream-retry-exit-code"' EXIT
source /mnt/lance/env.sh
export TMPDIR="$run_root/test-tmp/$variant-stream-retry"
mkdir -p "$TMPDIR"
export LANCE_ENABLE_UNSTABLE_DATA_OVERLAY_FILES=1
export LANCE_MEM_POOL_SIZE=1073741824
unset LANCE_BYPASS_SPILLING
cd "$checkout/python"
uv run --no-sync python - "$run_root" "$variant" <<'PY' > "$run_root/logs/${variant}-stream-retry.log" 2>&1
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

root, variant = Path(sys.argv[1]), sys.argv[2]
extension = Path(importlib.util.find_spec("lance.lance").origin).resolve()
test_file = root / "tests/test_stream_retry.py"
identity = {
    "variant": variant,
    "extension": str(extension),
    "sha256": hashlib.sha256(extension.read_bytes()).hexdigest(),
    "test_sha256": hashlib.sha256(test_file.read_bytes()).hexdigest(),
}
print(json.dumps(identity), flush=True)
code = pytest.main(["-q", str(test_file)])
assert hashlib.sha256(extension.read_bytes()).hexdigest() == identity["sha256"]
print(json.dumps(identity | {"pytest_exit_code": code}), flush=True)
sys.exit(code)
PY
