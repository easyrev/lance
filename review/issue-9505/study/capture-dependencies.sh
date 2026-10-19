#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
destination="$run_root/environment/dependencies-supplement-v1"
test ! -e "$destination"
mkdir "$destination"
source /mnt/lance/env.sh
date -u --iso-8601=seconds > "$destination/captured-at.txt"
for variant in U B P D CTX DB DP; do
    case "$variant" in
        U) checkout=/mnt/lance/checkouts/U_main ;;
        D) checkout=/mnt/lance/checkouts/K_check ;;
        *) checkout="/mnt/lance/checkouts/unified-9505-${variant}" ;;
    esac
    (
        cd "$checkout/python"
        uv pip freeze --python .venv/bin/python > "$destination/$variant.txt"
        uv run --no-sync python - <<'PY' > "$destination/$variant-core.json"
import importlib.metadata
import json
import platform

print(json.dumps({
    "python": platform.python_version(),
    "packages": {
        name: importlib.metadata.version(name)
        for name in ("numpy", "pyarrow", "pylance")
    },
}, indent=2))
PY
    )
done
sha256sum "$destination"/*.txt "$destination"/*.json > "$destination/SHA256SUMS"
