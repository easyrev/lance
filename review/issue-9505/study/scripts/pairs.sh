#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/hypotheses-9505-20261019
source /mnt/lance/env.sh
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/pairs-exit-code"' EXIT
test "$(cat "$run_root/logs/diagnostics-exit-code")" = 0
cd /mnt/lance/checkouts/U_main/python
uv run --no-sync python - <<'PY'
import hashlib
import json
from pathlib import Path
root=Path('/mnt/lance/hypotheses-9505-20261019')
freeze=json.loads((root/'freeze-v1.json').read_text())
def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
assert digest(freeze['binary']['path'])==freeze['binary']['sha256']
for name, expected in freeze['harness_hashes'].items():
    assert digest(root/name)==expected, name
for name, expected in freeze['full_tree_identity']['source_hashes'].items():
    assert digest(Path('/mnt/lance/checkouts/hypotheses-9505')/name)==expected, name
record=dict(freeze_v1_sha256=digest(root/'freeze-v1.json'),paired_plan_sha256=digest(root/'paired-plan.json'),
    global_config=json.loads((root/'config.json').read_text()),global_config_sha256=digest(root/'config.json'),
    binary_sha256=freeze['binary']['sha256'],source_and_harness_reverified=True)
(root/'paired-freeze.json').write_text(json.dumps(record,indent=2)+'\n')
PY
uv run --no-sync python "$run_root/scripts/run.py" pairs "$run_root/paired-plan.json"
date -u --iso-8601=seconds
