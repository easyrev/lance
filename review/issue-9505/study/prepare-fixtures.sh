#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
trap 'status=$?; printf "%s\n" "$status" > "$run_root/logs/fixture-setup-exit-code"' EXIT
source /mnt/lance/env.sh
cd /mnt/lance/checkouts/U_main/python
test "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs
printf '+cpu +memory\n' > /sys/fs/cgroup/cgroup.subtree_control
mkdir /sys/fs/cgroup/lance-unified-9505
test -z "$(cat /sys/fs/cgroup/lance-unified-9505/cgroup.procs)"
printf '+cpu +memory\n' > /sys/fs/cgroup/lance-unified-9505/cgroup.subtree_control
mkdir /sys/fs/cgroup/lance-unified-9505/preflight
for control in memory.max memory.swap.max memory.oom.group cgroup.kill cpu.max; do
    test -f "/sys/fs/cgroup/lance-unified-9505/preflight/$control"
done
rmdir /sys/fs/cgroup/lance-unified-9505/preflight
harness="$run_root/harness/harness.py"
uv run --no-sync python -m py_compile "$harness" "$run_root/harness/fixtures.py" "$run_root/harness/legacy_fixtures.py"
uv run --no-sync python "$harness" init --config "$run_root/harness/config.example.json"
uv run --no-sync python "$harness" freeze --name fixtures --variants U
uv run --no-sync python "$harness" import-fixtures --source-root /mnt/lance/killer-merge-20261018 --workloads tiny,string_null,condition_overlap,condition_reject,F16,Wn,Ws,dense_safe,R
uv run --no-sync python "$harness" import-fixtures --source-root /mnt/lance/killer-merge-admission-fixed-20261019 --workloads R_admission
uv run --no-sync python "$harness" generate --freeze fixtures --workloads N_dense,V_dense,late_jump,F64
date -u --iso-8601=seconds
