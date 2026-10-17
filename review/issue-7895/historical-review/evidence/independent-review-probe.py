import contextlib
import hashlib
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "/workspace/lance-7895/python/python")

import lance
import lance.lance as native
import pyarrow as pa
import pyarrow.dataset as pads
import pyarrow.parquet as pq
from lance.types import coerce_source

assert Path(native.__file__).resolve() == Path(
    "/workspace/lance-7895/python/python/lance/lance.abi3.so"
)
checks = []
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    schema = pa.schema(
        [pa.field("id", pa.int64(), metadata={"origin": "review"}),
         pa.field("value", pa.int64())],
        metadata={"version": "original"},
    )
    data = pa.Table.from_pydict(
        {"id": [0, 1, 2, 3, 4, 5], "value": [10, 11, 12, 13, 14, 15]},
        schema=schema,
    )
    source_uri = root / "source"
    lance.write_dataset(data, source_uri, max_rows_per_file=2)
    source = lance.dataset(source_uri, default_scan_options={
        "columns": ["value", "id"], "offset": 1, "limit": 4, "batch_size": 1,
    })
    adapted = coerce_source(source)
    assert adapted.mode == "replayable"
    expected = data.select(["value", "id"]).slice(1, 4)
    assert adapted.open_reader().read_all().equals(expected, check_metadata=True)
    assert adapted.open_reader().read_all().equals(expected, check_metadata=True)
    checks.append("dataset defaults preserve projection, offset, limit and metadata")

    target_uri = root / "target"
    lance.write_dataset(data, target_uri)
    commits = []

    @contextlib.contextmanager
    def lock(version):
        commits.append(version)
        if len(commits) == 1:
            def mutate():
                lance.dataset(target_uri).update({"value": "-1"})
                source.update({"value": "value + 1000"})
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(mutate).result(timeout=15)
        yield

    target = lance.dataset(target_uri, commit_lock=lock)
    target.merge_insert("id").when_matched_update_all().execute(adapted)
    assert commits == [2, 3]
    actual = target.to_table().sort_by("id")
    assert actual["value"].to_pylist() == [-1, 11, 12, 13, 14, -1]
    assert source.version == 2
    checks.append("source handle mutation during actual retry retains adapted snapshot")

    original = lance.dataset(source_uri, version=1)
    reverse_fragments = list(reversed(original.get_fragments()))
    fragment_source = coerce_source(original.scanner(fragments=reverse_fragments))
    assert fragment_source.mode == "replayable"
    expected_ids = [4, 5, 2, 3, 0, 1]
    assert fragment_source.open_reader().read_all()["id"].to_pylist() == expected_ids
    assert fragment_source.open_reader().read_all()["id"].to_pylist() == expected_ids
    checks.append("explicit fragment encounter order preserved on repeated scans")

    files = []
    for index in range(3):
        path = root / f"{index}.parquet"
        pq.write_table(data.slice(index * 2, 2), path)
        files.append(path)
    arrow = coerce_source(pads.dataset(list(reversed(files))))
    assert arrow.mode == "replayable"
    for _ in range(2):
        scanned = arrow.open_reader().read_all()
        assert scanned.schema.equals(data.schema, check_metadata=True)
        assert scanned["id"].to_pylist() == expected_ids
    checks.append("Arrow multi-file order and schema metadata preserved")

print(json.dumps({
    "package": lance.__file__, "extension": native.__file__,
    "extension_sha256": hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),
    "pyarrow": pa.__version__, "checks": checks,
}, indent=2))
