#!/usr/bin/env bash
set -euo pipefail

ROOT=/mnt/lance/bench-9617
HARNESS=$ROOT/harness
PROFILE=$ROOT/results/profiles
PY_UP=$ROOT/venv-upstream/bin/python
PY_PR=$ROOT/venv-pr/bin/python

cd "$HARNESS"
for rep in 1 2; do
  for mode in reused bounded; do
    name="pooldiag-1g-${mode}-default-r${rep}"
    start=$($PY_UP prep.py restore merge_insert_base | jq -r .version)
    /usr/bin/python3 -c \
      "from driver import read_tree, DATA; print(read_tree(DATA / 'target.lance') + read_tree(DATA / 'src-1g.parquet'))"
    tmp="$ROOT/tmp/$name"
    mkdir -p "$tmp"
    env TMPDIR="$tmp" /usr/bin/time -v "$PY_PR" pool_diag.py \
      --mode "$mode" \
      --pool-backend default \
      --tier 1g \
      --competitor-id 1608735 \
      --out "$PROFILE/$name.json" \
      >"$PROFILE/$name.log" 2>&1
    $PY_UP prep.py verify 1g 4171854 "$start" 2 >>"$PROFILE/$name.log"
    rmdir "$tmp"
    jq -c \
      '{mode,pool_backend,wall_s,cpu_s:(.user_s+.sys_s),max_rss_kib,pool_max:(.events|map(.pool_max)|max),first_commit_s:(.events|map(select(.event=="commit_enter" and .attempt==1))[0].t_s),first_commit_rss_kib:(.events|map(select(.event=="commit_enter" and .attempt==1))[0].smaps_rollup_Rss_kib),second_factory_s:(.events|map(select(.event=="factory_enter" and .call==2))[0].t_s),second_commit_rss_kib:(.events|map(select(.event=="commit_enter" and .attempt==2))[0].smaps_rollup_Rss_kib)}' \
      "$PROFILE/$name.json"
  done
done

$PY_UP prep.py restore merge_insert_base
