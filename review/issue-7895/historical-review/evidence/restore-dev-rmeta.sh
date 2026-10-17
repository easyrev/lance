#!/usr/bin/env bash
set -euo pipefail
source /workspace/issue-7895-evidence/env.sh
cd /workspace/lance-7895/python
uv run --frozen --no-sync python /workspace/issue-7895-evidence/restore-dev-rmeta.py
