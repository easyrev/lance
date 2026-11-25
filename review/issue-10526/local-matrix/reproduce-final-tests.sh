#!/usr/bin/env bash
set -eu
ev=$(cd "$(dirname "$0")" && pwd)
variant=$1
split=rust/lance-encoding/src/encodings/logical/primitive/wide_value_split.rs
cp "$ev/$variant.rs" "$split"
python3 "$ev/add-tests.py" "$split"
if [[ "$variant" == p2-compatible ]]; then
    python3 - "$ev/width-tests.rs" "$split" <<'PY'
from pathlib import Path
import sys
tests, target = map(Path, sys.argv[1:])
source = target.read_text()
before = '    fn plan_wide_binary_with_budget('
assert before in source
target.write_text(source.replace(before, tests.read_text() + before, 1))
PY
fi
rustfmt --edition 2024 "$split"
git diff --check
cargo test -q -p lance-encoding -p lance-file --lib --profile release-no-lto wide
