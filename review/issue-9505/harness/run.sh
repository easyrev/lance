#!/usr/bin/env bash
set -euo pipefail

root=/mnt/lance/issue-9505
variant=$1
run_id=$2
limit=$3
pool=$4
shift 4

if pgrep -x rustc >/dev/null || pgrep -x cargo >/dev/null; then
    echo "A build is active; benchmark aborted to avoid CPU interference." >&2
    exit 2
fi

# Warm target files outside the measured cgroup. Both repetitions measure
# warm local-storage reads; this is not a cold or remote-object-store benchmark.
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
    if [[ "${args[$i]}" == --uri ]]; then
        find "${args[$((i+1))]}/data" -type f -name '*.lance' -exec cat {} + >/dev/null
        break
    fi
done
mkdir -p "$root/results/$variant"
set +e
systemd-run --quiet --wait --pipe --collect --unit="lance9505-$variant-$run_id" \
    --property="MemoryMax=$limit" --property=MemorySwapMax=0 \
    --working-directory="$root/$variant/python" \
    /usr/bin/env LANCE_MEM_POOL_SIZE="$pool" \
    /usr/bin/time -v /root/.local/bin/uv run --no-sync python \
    "$root/harness/harness.py" "$@" \
    --output "$root/results/$variant/$run_id.json" \
    >"$root/results/$variant/$run_id.log" 2>&1
status=$?
set -e
echo "$status" > "$root/results/$variant/$run_id.exit"
journalctl --no-pager -u "lance9505-$variant-$run_id" -n 8 > "$root/results/$variant/$run_id.journal"
cat "$root/results/$variant/$run_id.log"
exit "$status"
