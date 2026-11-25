#!/usr/bin/env bash
set -eu
ev=$(cd "$(dirname "$0")" && pwd)
split=rust/lance-encoding/src/encodings/logical/primitive/wide_value_split.rs
example=rust/lance-file/examples/writer10526.rs
base=cb8c25692
fix=1fee2feab
branch=t3/10526-wide-value-page-split
cleanup() {
    rm -f "$example"
    if git diff --name-only | grep -qx "$split"; then git restore -- "$split"; fi
    git switch "$branch"
}
trap cleanup EXIT
build() {
    local variant=$1
    cargo build -p lance-file --example writer10526 --profile release-no-lto --message-format=json > "$ev/$variant.cargo.jsonl" 2> "$ev/$variant.build.log"
    python3 - "$ev" "$variant" <<'PY'
import json, shutil, sys
from pathlib import Path
root, variant = Path(sys.argv[1]), sys.argv[2]
for line in (root / f'{variant}.cargo.jsonl').read_text().splitlines():
    item = json.loads(line)
    if item.get('executable') and item['target']['name'] == 'writer10526':
        shutil.copy2(item['executable'], root / f'writer-{variant}')
        break
else:
    raise RuntimeError('Missing benchmark executable')
PY
}
git switch --detach "$base"
cp "$ev/writer10526.rs" "$example"
build baseline
git switch --detach "$fix"
build fix
cp "$ev/p1.rs" "$split"
build p1
cp "$ev/p2.rs" "$split"
build p2
