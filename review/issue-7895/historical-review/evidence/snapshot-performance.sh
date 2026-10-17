#!/usr/bin/env bash
set -euo pipefail
source /workspace/issue-7895-evidence/env.sh
label=$1
source_package=$2
native=$3
output_package=$4
evidence=/workspace/issue-7895-evidence
cd /workspace/lance-7895/python
uv run --no-sync python - "$source_package" "$output_package" <<'PY'
from pathlib import Path
import shutil
import sys
source, target = map(Path, sys.argv[1:])
target.mkdir()
shutil.copytree(source / 'lance', target / 'lance',
                ignore=shutil.ignore_patterns('*.so', '*.so.gz', '__pycache__'))
PY
# Debug sections are not loaded by the runtime. Preserve the full original in a
# compressed archive and copy its executable sections unchanged into the package.
objcopy --strip-debug "$native" "$output_package/lance/lance.abi3.so"
uv run --no-sync python "$evidence/check-elf-sections.py" "$native" "$output_package/lance/lance.abi3.so" > "$evidence/$label-elf-sections.json"
gzip -1 -c -- "$native" > "$evidence/$label-full.so.gz"
sha256sum "$native" "$output_package/lance/lance.abi3.so" "$evidence/$label-full.so.gz" > "$evidence/$label.sha256"
# This generated cached library will be rebuilt after the source edit. Its debug
# information is now preserved in the archive; avoid storing it twice on disk.
strip --strip-debug "$native"
