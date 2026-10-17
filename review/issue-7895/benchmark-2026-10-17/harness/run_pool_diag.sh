#!/usr/bin/env bash
set -euo pipefail

ROOT=/mnt/lance/bench-9617
HARNESS=$ROOT/harness
PROFILE=$ROOT/results/profiles
PY_UP=$ROOT/venv-upstream/bin/python
PY_PR=$ROOT/venv-pr/bin/python
TIER=1g
EXPECTED_ROWS=4171854
COMPETITOR_ID=1608735

cd "$HARNESS"

for spec in reused:default fresh:default bounded:default reused:system; do
  mode=${spec%%:*}
  pool=${spec##*:}
  name="pooldiag-${TIER}-${mode}-${pool}"
  start=$($PY_UP prep.py restore merge_insert_base | jq -r .version)
  /usr/bin/python3 -c \
    "from driver import read_tree, DATA; print(read_tree(DATA / 'target.lance') + read_tree(DATA / 'src-${TIER}.parquet'))"
  tmp="$ROOT/tmp/$name"
  mkdir -p "$tmp"
  env TMPDIR="$tmp" /usr/bin/time -v "$PY_PR" pool_diag.py \
    --mode "$mode" \
    --pool-backend "$pool" \
    --tier "$TIER" \
    --competitor-id "$COMPETITOR_ID" \
    --out "$PROFILE/$name.json" \
    >"$PROFILE/$name.log" 2>&1
  $PY_UP prep.py verify "$TIER" "$EXPECTED_ROWS" "$start" 2 \
    >>"$PROFILE/$name.log"
  rmdir "$tmp"
  jq -c \
    '{mode,pool_backend_requested,pool_backend,factory_calls,commit_attempts,wall_s,max_rss_kib,pool_max:(.events|map(.pool_max)|max),rss_after_first_kib:(.events|map(select(.event=="commit_enter" and .attempt==1))[0].smaps_rollup_Rss_kib),rss_before_second_kib:(.events|map(select(.event=="factory_enter" and .call==2))[0].smaps_rollup_Rss_kib),rss_after_second_kib:(.events|map(select(.event=="commit_enter" and .attempt==2))[0].smaps_rollup_Rss_kib)}' \
    "$PROFILE/$name.json"
done

$PY_UP prep.py restore merge_insert_base
