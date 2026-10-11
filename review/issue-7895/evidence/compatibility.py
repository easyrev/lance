"""Exercise the source contract with an explicit package and Arrow installation."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

parser = argparse.ArgumentParser()
parser.add_argument("--package", required=True)
parser.add_argument("--single-worker", action="store_true")
args = parser.parse_args()
sys.path.insert(0, args.package)

import lance
import lance.lance as native
from lance.types import WriteSource, coerce_source
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as pads
import pyarrow.parquet as pq

checks = []
data = pa.table({"id": [0, 1, 2, 3], "value": [10, 11, 12, 13]})
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    source = lance.write_dataset(data, root / "source", max_rows_per_file=2)
    pinned = coerce_source(source)
    source.update({"value": "value + 100"})
    assert pinned.open_reader().read_all() == data
    assert pinned.open_reader().read_all() == data
    checks.append("Lance version, order and repeated reader")

    pq.write_table(data.slice(0, 2), root / "0.parquet")
    pq.write_table(data.slice(2), root / "1.parquet")
    arrow = pads.dataset([root / "0.parquet", root / "1.parquet"])
    for item in [arrow, pads.dataset(data), pads.dataset([pads.dataset(data)])]:
        adapted = coerce_source(item)
        assert adapted.mode == "replayable"
        assert adapted.open_reader().read_all() == data
        assert adapted.open_reader().read_all() == data
    checks.append("Arrow filesystem, memory and union repeatability")
    filtered = coerce_source(arrow.filter(pc.field("id") > 1))
    assert filtered.mode == "streaming"
    assert filtered.open_reader().read_all() == data.slice(2)
    scanner = pads.Scanner.from_batches(iter(data.to_batches()), schema=data.schema)
    adapted = coerce_source(scanner)
    assert adapted.mode == "streaming"
    assert adapted.open_reader().read_all() == data
    checks.append("Arrow filter and one-shot scanner fallback")

    class ExternalSource:
        pass

    calls = []
    competing_versions = []

    def reader():
        calls.append(threading.get_ident())
        if args.single_worker and len(calls) == 1:
            # The factory runs on a blocking thread, so one async worker remains
            # available for this competing transaction and the source scan.
            competing = lance.dataset(target_uri)
            competing.update({"value": "-1"})
            competing_versions.append(competing.version)
        # This call waits on Lance's runtime and must execute off its async worker.
        return source.scanner(batch_size=1).to_reader()

    @coerce_source.register(ExternalSource)
    def adapt_external(value, schema=None):
        return WriteSource(source.schema, reader)

    target_uri = root / "target"
    lance.write_dataset(data, target_uri)
    commits = []

    @contextlib.contextmanager
    def lock(version):
        commits.append(version)
        if not args.single_worker and len(commits) == 1:
            errors = []

            def update():
                try:
                    competing = lance.dataset(target_uri)
                    competing.update({"value": "-1"})
                    competing_versions.append(competing.version)
                except BaseException as error:
                    errors.append(error)

            worker = threading.Thread(target=update, daemon=True)
            worker.start()
            worker.join(20)
            assert not worker.is_alive()
            if errors:
                raise errors[0]
        yield

    target = lance.dataset(target_uri, commit_lock=lock)
    target.merge_insert("id").when_matched_update_all().conflict_retries(2).execute(
        ExternalSource()
    )
    expected_calls = 2
    assert len(calls) == expected_calls, calls
    # The early update is detected before commit_lock is entered. Both paths
    # must still execute the source twice and commit exactly version 3.
    assert commits == ([3] if args.single_worker else [2, 3]), commits
    assert competing_versions == [2], competing_versions
    assert all(call != threading.get_ident() for call in calls)
    assert target.version == expected_calls + 1
    assert target.to_table().sort_by("id") == source.to_table().sort_by("id")
    checks.append("external factory with real retry" + (" and one worker" if args.single_worker else ""))

print(json.dumps({
    "python": sys.version,
    "pyarrow": pa.__version__,
    "package": lance.__file__,
    "extension": native.__file__,
    "extension_sha256": hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),
    "tokio_workers": os.environ.get("TOKIO_WORKER_THREADS"),
    "factory_calls": len(calls),
    "commit_versions": commits,
    "competing_versions": competing_versions,
    "checks": checks,
}, indent=2))
