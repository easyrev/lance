#!/usr/bin/env bash
set -eu
ev=$(cd "$(dirname "$0")" && pwd)
split=rust/lance-encoding/src/encodings/logical/primitive/wide_value_split.rs
example=rust/lance-file/examples/writer10526.rs
cleanup() {
    rm -f "$example"
    git restore -- "$split"
}
trap cleanup EXIT
cp "$ev/writer10526.rs" "$example"
for variant in p1-compatible p2-compatible; do
    cp "$ev/$variant.rs" "$split"
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
done
