import tempfile
import threading

import lance
import pyarrow as pa
from lance.types import WriteSource


def event(label):
    print(label, threading.get_ident(), threading.current_thread().name, flush=True)


with tempfile.TemporaryDirectory() as root:
    data = pa.table({"id": [1], "value": [2]})
    target = lance.write_dataset(data, root + "/target")
    nested = lance.write_dataset(data, root + "/nested")

    class SourceError(Exception):
        def __str__(self):
            event("error_str_start")
            print("nested_count", nested.count_rows(), flush=True)
            event("error_str_end")
            return "custom source failure"

    def factory():
        event("factory")
        raise SourceError()

    event("main")
    source = WriteSource(data.schema, factory, mode="replayable")
    for operation in ("update", "insert", "upsert", "analyze"):
        print("operation", operation, flush=True)
        builder = target.merge_insert("id")
        if operation in ("update", "upsert", "analyze"):
            builder.when_matched_update_all()
        if operation in ("insert", "upsert"):
            builder.when_not_matched_insert_all()
        try:
            if operation == "analyze":
                print("analyze_result", builder.analyze_plan(source), flush=True)
            else:
                builder.execute(source)
        except BaseException as error:
            event("caught")
            print(type(error).__name__, str(error), flush=True)
