import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/workspace/lance-7895/python/python")
import lance
import lance.lance as native
import pyarrow as pa
from lance.types import WriteSource

extension_hash = hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest()
assert extension_hash == os.environ["REVIEW_EXPECTED_EXTENSION_SHA256"]
data = pa.table({"id": [1], "value": [2]})
observed = []
with tempfile.TemporaryDirectory() as root:
    target = lance.write_dataset(data, root)
    for mode in ["replayable", "streaming"]:
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
            builder = target.merge_insert("id").when_matched_update_all()
            try:
                builder.analyze_plan(WriteSource(data.schema, factory, mode=mode))
            except (ValueError, OSError) as error:
                assert failure in str(error), str(error)
                observed.append({"mode": mode, "failure": failure,
                                 "error_type": type(error).__name__})
            else:
                raise AssertionError(f"analyze_plan silently accepted {mode}/{failure}")
            assert lance.dataset(root).version == 1
            assert lance.dataset(root).to_table() == data
    for kind in ["materialized", "streaming", "replayable"]:
        source = {
            "materialized": lambda: data,
            "streaming": data.to_reader,
            "replayable": lambda: WriteSource(data.schema, data.to_reader),
        }[kind]()
        report = target.merge_insert("id").when_matched_update_all().analyze_plan(source)
        assert "num_updated_rows=1" in report
        assert lance.dataset(root).version == 1
        observed.append({"kind": kind, "successful_report": True})
    assert "Lance" in target.scanner().analyze_plan()
    observed.append({"ordinary_scanner_analyze": True})
print(json.dumps({"extension": native.__file__, "extension_sha256": extension_hash,
                  "pyarrow": pa.__version__, "checks": observed}, indent=2))
