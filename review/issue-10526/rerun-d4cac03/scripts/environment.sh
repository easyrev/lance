#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
trap 'status=$?; echo "$status" > "$raw/environment.exit"' EXIT
space
mkdir -p "$raw/imports"
for variant in base head; do
    resolve "$variant"
    sha256sum -c "$raw/extension-$variant.sha256"
    pip --python "$environment/bin/python" freeze --all > "$raw/freeze-$variant.txt"
    sed -E '/^pylance(==| @ )/d; /^-e .*#egg=pylance(&|$)/d; /^-e .*\/python$/d' \
        "$raw/freeze-$variant.txt" > "$raw/freeze-dependencies-$variant.txt"
    [[ $(($(wc -l < "$raw/freeze-$variant.txt") - $(wc -l < "$raw/freeze-dependencies-$variant.txt"))) == 1 ]]
    { "$environment/bin/python" -V; readlink -f "$environment/bin/python"; sha256sum "$(readlink -f "$environment/bin/python")"; } > "$raw/python-$variant.txt"
    run "$variant" -c 'import lance.lance; from pathlib import Path; print(Path(lance.lance.__file__).resolve())' > "$raw/import-extension-$variant.txt"
    [[ $(cat "$raw/import-extension-$variant.txt") == "$extension" ]]
    site=$environment/lib/python3.12/site-packages
    (cd "$site"; find . -type f ! -path '*/__pycache__/*' ! -name 'pylance.pth' ! -path './pylance-*.dist-info/*' -print0 | sort -z | xargs -0 sha256sum) > "$raw/site-$variant.sha256"
    (cd "$checkout/python/python/lance"; find . -type f ! -path '*/__pycache__/*' ! -name 'lance.abi3.so' -print0 | sort -z | xargs -0 sha256sum) > "$raw/package-$variant.sha256"
done
[[ $(cut -d ' ' -f 1 "$raw/extension-base.sha256") != $(cut -d ' ' -f 1 "$raw/extension-head.sha256") ]]
python3 "$disk/scripts/audit-env.py" "$disk" > "$raw/environment-match.txt"
for trial in 1 2 3 4 5; do
    for variant in base head; do
        run "$variant" -c 'import resource; import lance; print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)' > "$raw/imports/$variant-$trial.txt"
    done
done
