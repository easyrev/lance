#!/usr/bin/env bash
set -euo pipefail
source /workspace/issue-7895-evidence/env.sh
cd /workspace/lance-7895/python
evidence=/workspace/issue-7895-evidence
output=${VALIDATION_OUTPUT:-"$evidence/review-fix"}
mkdir -p "$output"
export TOKIO_WORKER_THREADS=4 RAYON_NUM_THREADS=4 OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
export PYO3_PYTHON=/workspace/lance-7895/python/.venv/bin/python
export PYO3_ENVIRONMENT_SIGNATURE=cpython-3.12-64bit
export CARGO_BUILD_JOBS=2
uv run --no-sync python -c 'import hashlib, json, pathlib, sys, lance, lance.lance as native, pyarrow; print(json.dumps({"python":sys.version,"pyarrow":pyarrow.__version__,"package":lance.__file__,"extension":native.__file__,"sha256":hashlib.sha256(pathlib.Path(native.__file__).read_bytes()).hexdigest()},indent=2))' > "$output/provenance.json"
uv run --no-sync pytest -q python/tests/test_dataset.py -k 'merge_insert or source or input_data or pydantic or default_scan_options or roundtrip_reader or schema_metadata' > "$output/python-provider.log" 2>&1
uv run --no-sync pytest -q python/tests/test_fragment.py python/tests/test_udf.py python/tests/test_json.py python/tests/test_mem_wal.py > "$output/python-write-regressions.log" 2>&1
uv run --no-sync pytest -q --doctest-modules python/lance/types.py > "$output/python-doctest.log" 2>&1
uv run --no-sync python "$evidence/compatibility.py" --package /workspace/lance-7895/python/python > "$output/compatibility-current.json" 2> "$output/compatibility-current.stderr"
TOKIO_WORKER_THREADS=1 timeout 90s uv run --no-sync python "$evidence/compatibility.py" --package /workspace/lance-7895/python/python --single-worker > "$output/compatibility-single-worker.json" 2> "$output/compatibility-single-worker.stderr"
uv run --no-project --python 3.12 --with pyarrow==14.0.2 --with 'numpy<2' --with 'lance-namespace>=0.13,<0.14' python "$evidence/compatibility.py" --package /workspace/lance-7895/python/python > "$output/compatibility-arrow14.json" 2> "$output/compatibility-arrow14.stderr"
uv run --no-sync make lint UV_RUN='uv run --frozen --no-sync' > "$output/lint-full.log" 2>&1
cargo clippy --all --tests --benches -- -D warnings > "$output/clippy-all.log" 2>&1
EVIDENCE_DIR="$output" "$evidence/run-provider-tests.sh"
