import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/workspace/lance-7895/python/python")
import lance
import lance.lance as native
import pyarrow as pa
from lance.types import WriteSource

data = pa.table({"id": [1], "value": [2]})
results = []
with tempfile.TemporaryDirectory() as root:
    target = lance.write_dataset(data, root)
    for failure in ["factory", "schema", "batch"]:
        def factory():
            if failure == "factory":
                raise ValueError("independent factory failure")
            if failure == "schema":
                return data.replace_schema_metadata({"unexpected": "value"}).to_reader()
            def batches():
                raise ValueError("independent batch failure")
                yield
            return pa.RecordBatchReader.from_batches(data.schema, batches())
        for operation in ["execute", "analyze_plan"]:
            builder = target.merge_insert("id").when_matched_update_all()
            try:
                result = getattr(builder, operation)(WriteSource(data.schema, factory))
                observed = {"returned": str(result).splitlines()[0]}
            except Exception as error:
                observed = {"error_type": type(error).__name__, "error": str(error)}
            results.append({"failure": failure, "operation": operation, **observed})
        assert lance.dataset(root).version == 1
print(json.dumps({
    "extension": native.__file__,
    "extension_sha256": hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),
    "results": results,
}, indent=2))
