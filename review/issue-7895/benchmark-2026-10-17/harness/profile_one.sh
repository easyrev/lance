#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 {perf|heaptrack} {upstream|pr} {lance|parquet}" >&2
  exit 2
fi

tool=$1
variant=$2
source_kind=$3

case "$tool" in
  perf|heaptrack) ;;
  *) echo "unknown profiler: $tool" >&2; exit 2 ;;
esac
case "$variant" in
  upstream|pr) ;;
  *) echo "unknown variant: $variant" >&2; exit 2 ;;
esac
case "$source_kind" in
  lance|parquet) ;;
  *) echo "unknown source: $source_kind" >&2; exit 2 ;;
esac

source /mnt/lance/env.sh
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

bench=/mnt/lance/bench-9617
harness=$bench/harness
profiles=$bench/results/profiles
python=$bench/venv-$variant/bin/python
prep_python=$bench/venv-upstream/bin/python
run_id="profile-$tool-$variant-$source_kind-$(date +%Y%m%dT%H%M%S)"
tmpdir=$bench/tmp/$run_id
result=$profiles/$run_id.json
log=$profiles/$run_id.log
competitor_id=$(jq -r .competitor_id "$bench/data/src-1g.json")

mkdir -p "$profiles" "$tmpdir"

cleanup() {
  rm -rf -- "$tmpdir"
  "$prep_python" "$harness/prep.py" restore merge_insert_base >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$prep_python" "$harness/prep.py" restore merge_insert_base >"$profiles/$run_id.restore.json"

if [[ "$source_kind" == lance ]]; then
  source_path=$bench/data/src-1g.lance
else
  source_path=$bench/data/src-1g.parquet
fi
find "$bench/data/target.lance" "$source_path" -type f -print0 \
  | xargs -0 -r cat >/dev/null

command=(
  "$python" "$harness/run_merge.py"
  --tier 1g
  --source "$source_kind"
  --conflict 1
  --competitor-id "$competitor_id"
  --out "$result"
)

if [[ "$tool" == perf ]]; then
  data=$profiles/$run_id.perf.data
  /usr/bin/time -v env TMPDIR="$tmpdir" \
    perf record -q -F 99 -e cpu-clock --call-graph dwarf,16384 \
    -o "$data" -- "${command[@]}" >"$log" 2>&1
  perf report --stdio -g none --no-inline --no-children --percent-limit 0.2 \
    -i "$data" --sort comm,dso,symbol 2>"$profiles/$run_id.perf-symbols.stderr" \
    | c++filt >"$profiles/$run_id.perf-symbols.txt"
else
  prefix=$profiles/$run_id.heaptrack
  /usr/bin/time -v env TMPDIR="$tmpdir" \
    heaptrack --record-only -o "$prefix" "${command[@]}" >"$log" 2>&1
fi

jq -e '.commit_attempts == 2' "$result" >/dev/null
start_version=$(jq -r .start_version "$result")
verify=$("$prep_python" "$harness/prep.py" verify 1g 4171854 "$start_version" 2)
echo "$verify" >"$profiles/$run_id.verify.json"
echo "$verify" | jq -e '.ok == true' >/dev/null

echo "$run_id"
