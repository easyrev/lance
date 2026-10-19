#!/usr/bin/env bash
set -euo pipefail
variant="$1"
run_root=/mnt/lance/unified-9505-20261019
case "$variant" in
    U) checkout=/mnt/lance/checkouts/U_main ;;
    D) checkout=/mnt/lance/checkouts/K_check ;;
    *) checkout="/mnt/lance/checkouts/unified-9505-${variant}" ;;
esac
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/${variant}-python-exit-code"' EXIT
source /mnt/lance/env.sh
export TMPDIR="$run_root/test-tmp/$variant"
mkdir -p "$TMPDIR"
export LANCE_ENABLE_UNSTABLE_DATA_OVERLAY_FILES=1
export LANCE_MEM_POOL_SIZE=1073741824
unset LANCE_BYPASS_SPILLING
cd "$checkout/python"
uv run --no-sync python - "$run_root" "$variant" <<'PY' > "$run_root/logs/${variant}-python-tests.log" 2>&1
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

root, variant = Path(sys.argv[1]), sys.argv[2]
extension = Path(importlib.util.find_spec("lance.lance").origin).resolve()
identity = {"variant": variant, "extension": str(extension), "sha256": hashlib.sha256(extension.read_bytes()).hexdigest()}
print(json.dumps(identity), flush=True)
code = pytest.main(["-q", "python/tests/test_dataset.py", str(root / "tests/test_merge_semantics.py"), "-k", "merge_insert or test_merge_semantics"])
assert hashlib.sha256(extension.read_bytes()).hexdigest() == identity["sha256"]
print(json.dumps(identity | {"pytest_exit_code": code}), flush=True)
sys.exit(code)
PY
