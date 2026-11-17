#!/usr/bin/env bash
# Install the #7207 reproduction harness into a Lance checkout.
#
# Usage: bash apply.sh            (from anywhere inside the target checkout)
#
# Copies repro_7207.rs into rust/lance/src/io/commit/ and registers it in
# rust/lance/src/io/commit.rs right after `pub mod namespace_manifest;`.
# Run `git checkout -- rust/lance/src/io` afterwards to undo it.
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(git rev-parse --show-toplevel)

commit_rs="$repo_root/rust/lance/src/io/commit.rs"
anchor='pub mod namespace_manifest;'

cp "$script_dir/repro_7207.rs" "$repo_root/rust/lance/src/io/commit/repro_7207.rs"

if grep -qxF 'mod repro_7207;' "$commit_rs"; then
  echo "harness already registered in $commit_rs"
  exit 0
fi

if ! grep -qxF "$anchor" "$commit_rs"; then
  echo "error: '$anchor' not found in $commit_rs" >&2
  exit 1
fi

tmp=$(mktemp)
awk -v anchor="$anchor" '
  { print }
  $0 == anchor {
    print "#[cfg(test)]"
    print "mod repro_7207;"
  }
' "$commit_rs" > "$tmp"
mv "$tmp" "$commit_rs"

echo "installed repro_7207.rs and registered it in $commit_rs"
