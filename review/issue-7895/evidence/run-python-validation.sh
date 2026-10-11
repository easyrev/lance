#!/usr/bin/env bash
set -euo pipefail
source /workspace/issue-7895-evidence/env.sh
cd /workspace/lance-7895/python
export TOKIO_WORKER_THREADS=4
export RAYON_NUM_THREADS=4
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
uv run --no-sync python -c 'import hashlib, json, pathlib, sys, lance, lance.lance as native, pyarrow; print(json.dumps({"python":sys.version,"pyarrow":pyarrow.__version__,"package":lance.__file__,"extension":native.__file__,"sha256":hashlib.sha256(pathlib.Path(native.__file__).read_bytes()).hexdigest()},indent=2))' > /workspace/issue-7895-evidence/candidate-dev-provenance.json
uv run --no-sync pytest -q python/tests/test_dataset.py -k 'merge_insert or source or input_data or pydantic or default_scan_options or roundtrip_reader or schema_metadata' > /workspace/issue-7895-evidence/python-first-provider.log 2>&1
uv run --no-sync pytest -q python/tests/test_fragment.py python/tests/test_udf.py python/tests/test_json.py > /workspace/issue-7895-evidence/python-write-regressions.log 2>&1
uv run --no-sync python /workspace/issue-7895-evidence/compatibility.py --package /workspace/lance-7895/python/python > /workspace/issue-7895-evidence/compatibility-current.json 2> /workspace/issue-7895-evidence/compatibility-current.stderr
TOKIO_WORKER_THREADS=1 timeout 90s uv run --no-sync python /workspace/issue-7895-evidence/compatibility.py --package /workspace/lance-7895/python/python --single-worker > /workspace/issue-7895-evidence/compatibility-single-worker.json 2> /workspace/issue-7895-evidence/compatibility-single-worker.stderr
uv run --no-project --python 3.12 --with pyarrow==14.0.2 --with 'numpy<2' --with 'lance-namespace>=0.13,<0.14' python /workspace/issue-7895-evidence/compatibility.py --package /workspace/lance-7895/python/python > /workspace/issue-7895-evidence/compatibility-arrow14.json 2> /workspace/issue-7895-evidence/compatibility-arrow14.stderr
