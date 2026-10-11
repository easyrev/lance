#!/usr/bin/env bash
set -euo pipefail

source /workspace/issue-7895-evidence/env.sh
export CARGO_BUILD_JOBS=2
cd /workspace/lance-7895/python

evidence_dir=${EVIDENCE_DIR:-/workspace/issue-7895-evidence}
mkdir -p "$evidence_dir"
python_runtime=/opt/codex/runtimes/codex-primary-runtime/dependencies/python
export PYO3_PYTHON=/workspace/lance-7895/python/.venv/bin/python
# Match maturin's recorded PyO3 build-script environment to retain its cache.
export PYO3_ENVIRONMENT_SIGNATURE=cpython-3.12-64bit

# Keep extension-module enabled. Flags after -- affect only the test harness,
# supplying the libpython linkage that an extension normally gets from its host.
# --no-sync prevents uv from rebuilding the installed extension implicitly.
uv run --frozen --no-sync cargo rustc --locked --tests --message-format=json -- \
    -L "native=$python_runtime/lib" \
    -l dylib=python3.12 \
    -C "link-arg=-Wl,-rpath,$python_runtime/lib" \
    -C debuginfo=0 \
    -C strip=debuginfo \
    > "$evidence_dir/provider-test-build.jsonl" \
    2> "$evidence_dir/provider-test-build.log"

uv run --frozen --no-sync python - "$evidence_dir/provider-test-build.jsonl" \
    > "$evidence_dir/provider-test-executable.txt" <<'PY'
import json
import os
import sys

artifacts = []
with open(sys.argv[1], encoding="utf-8") as build_log:
    for line in build_log:
        event = json.loads(line)
        if event.get("reason") == "compiler-artifact":
            artifacts.append(event)

executables = {
    event["executable"]
    for event in artifacts
    if event.get("executable")
    and event["target"]["name"] == "lance"
    and event["profile"]["test"]
}
root_package_ids = {
    event["package_id"]
    for event in artifacts
    if event.get("executable") in executables
}
if len(executables) != 1:
    raise RuntimeError(f"Expected one Lance test executable, got {executables!r}")
executable = executables.pop()
if not os.path.isabs(executable) or not os.access(executable, os.X_OK):
    raise RuntimeError(f"Invalid test executable: {executable!r}")
print(executable)

rebuilt_dependencies = sorted(
    {
        event["package_id"]
        for event in artifacts
        if not event["fresh"]
        and event["package_id"] not in root_package_ids
        and "custom-build" not in event["target"]["kind"]
    }
)
with open(
    os.path.join(os.path.dirname(sys.argv[1]), "provider-test-cache.json"),
    "w",
    encoding="utf-8",
) as cache_log:
    json.dump({"rebuilt_dependencies": rebuilt_dependencies}, cache_log, indent=2)
    cache_log.write("\n")
PY

IFS= read -r provider_test_binary < "$evidence_dir/provider-test-executable.txt"
# The managed Python distribution has a relocatable prefix. Make that prefix
# explicit when libpython is embedded in the Rust test executable.
if PYTHONHOME="$python_runtime" timeout 90s "$provider_test_binary" \
    dataset::replayable::tests --nocapture \
    > "$evidence_dir/provider-tests.log" 2>&1; then
    cat "$evidence_dir/provider-tests.log"
else
    cat "$evidence_dir/provider-tests.log" >&2
    exit 1
fi
