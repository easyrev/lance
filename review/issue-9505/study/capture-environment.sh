#!/usr/bin/env bash
set -euo pipefail
run_root=/mnt/lance/unified-9505-20261019
mkdir -p "$run_root/environment"
source /mnt/lance/env.sh
date -u --iso-8601=seconds > "$run_root/environment/captured-at.txt"
uname -a > "$run_root/environment/uname.txt"
lscpu > "$run_root/environment/lscpu.txt"
free -b > "$run_root/environment/memory.txt"
df -B1 /mnt/lance > "$run_root/environment/disk.txt"
findmnt /mnt/lance > "$run_root/environment/mount.txt"
ulimit -a > "$run_root/environment/ulimit.txt"
rustc -Vv > "$run_root/environment/rustc.txt"
cargo -V > "$run_root/environment/cargo.txt"
uv --version > "$run_root/environment/uv.txt"
cp /mnt/lance/env.sh "$run_root/environment/env.sh"
cp /mnt/lance/validation-9505/review/issue-9505/harness/profile.mk "$run_root/environment/profile.mk"
git -C /mnt/lance/checkouts/U_main rev-parse HEAD > "$run_root/environment/U-head.txt"
git -C /mnt/lance/checkouts/U_main status --porcelain > "$run_root/environment/U-status.txt"
git -C /mnt/lance/checkouts/K_check diff --binary > "$run_root/environment/D-applied.patch"
sha256sum /mnt/lance/checkouts/U_main/python/python/lance/lance.abi3.so /mnt/lance/checkouts/K_check/python/python/lance/lance.abi3.so > "$run_root/environment/reused-binaries.sha256"
cd /mnt/lance/checkouts/U_main/python
uv pip freeze > "$run_root/environment/U-dependencies.txt"
uv run --no-sync python -c 'import sys, pyarrow, lance; print(sys.version); print(pyarrow.__version__); print(lance.__version__)' > "$run_root/environment/U-python.txt"
