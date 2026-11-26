#!/usr/bin/env bash
set -euo pipefail
task=/dev/shm/lance-10526/shared-buffer
raw=$task/raw
scripts=$(realpath "$(dirname "$0")")
trap 'status=$?; echo "$status" > "$raw/phase1-job.exit"' EXIT
wait_for_build() {
    local name=$1
    until [[ -s $raw/$name.exit ]]; do
        sleep 10
    done
    [[ $(cat "$raw/$name.exit") == 0 ]]
}
wait_for_build build-pure
# Keep a single copy when the installed editable module is byte-identical to Cargo's output.
pure_extension=/root/lance/shared-buffer-pure/python/python/lance/lance.abi3.so
pure_binary=$task/target-pure/release-with-debug/liblance.so
if [[ -f $pure_extension && -f $pure_binary ]] && cmp -s "$pure_extension" "$pure_binary"; then
    mkdir -p "$task/binaries"
    link=$task/binaries/pure-lance.abi3.so
    ln "$pure_binary" "$link"
    ln -s "$link" "$pure_extension.link"
    mv -T "$pure_extension.link" "$pure_extension"
    sha256sum "$link" > "$raw/extension-pure-relocation.sha256"
    if (( $(df -B1 --output=avail /dev/shm | tail -1) < 22 * 1024**3 )); then
        cargo clean --target-dir "$task/target-pure" > "$raw/clean-target-pure.log" 2>&1
    fi
fi
wait_for_build build-var-job
bash "$scripts/phase1.sh" > "$raw/phase1.log" 2>&1
