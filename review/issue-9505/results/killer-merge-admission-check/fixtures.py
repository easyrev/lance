"""Deterministic full-schema workload for the merge admission counterexample."""

import hashlib
import json

MIB = 1 << 20


def workloads():
    return {"R_admission": dict(
        name="R_admission", seed=9505, epoch=1,
        rows=1_000_000, columns=44, fragment_rows=100_000,
        source_rows=3_000_000, batch_rows=32768,
        full=True, binary=0, dense=False,
    )}


def schema(spec, source=False):
    import pyarrow as pa

    if spec.get("small_string"):
        fields = [("id", pa.string()), ("value", pa.int64())]
        if not source:
            fields += [("keep", pa.string()), ("guard", pa.int64()),
                       ("row_marker", pa.int64())]
        return pa.schema(fields)
    if source and not spec["full"]:
        names = ["id", "new_payload"] if spec.get("source_binary") else ["id", "c0", "c1"]
    else:
        names = ["id"] + [f"c{i}" for i in range(spec["columns"] - 1)]
        if spec["binary"]:
            names += ["payload", "new_payload", "row_marker"]
    return pa.schema([(name, pa.large_binary() if name in ("payload", "new_payload")
                       else pa.int64()) for name in names])


def values(ids, column, epoch=0):
    import numpy as np

    x = ids.astype(np.uint64) ^ np.uint64(9505 + column * 104729)
    with np.errstate(over="ignore"):
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    x ^= x >> np.uint64(31)
    return (x & np.uint64((1 << 40) - 1)).astype(np.int64) + epoch * (1 << 42)


def payload(marker, size, epoch=0):
    import numpy as np

    return np.random.default_rng(9505 + int(marker) * 17 + epoch * 10077).bytes(size)


def keys_for(spec):
    import numpy as np

    if spec["full"]:
        return None
    if spec["dense"]:
        return np.arange(spec["source_rows"], dtype=np.int64)
    keys = np.linspace(0, spec["rows"] - 1, spec["source_rows"], dtype=np.int64)
    return np.random.default_rng(9505).permutation(keys)


def string_table(source=False, expected=False):
    import pyarrow as pa

    if source:
        return pa.table({"id": [None, "a", "b", "c", "d", "missing"],
                         "value": pa.array([None, None, 10, 11, 12, 13], type=pa.int64())})
    return pa.table({
        "id": [None, "a", "b", "c", "d", "e"],
        "value": pa.array([100, None if expected else 101, 102, 103,
                           12 if expected else 104, 105], type=pa.int64()),
        "keep": ["null-key", None, "b-old", "c-old", "d-old", None],
        "guard": pa.array([1, 1, 0, None, 1, 1], type=pa.int64()),
        "row_marker": pa.array(range(6), type=pa.int64()),
    })


def target_batches(spec):
    import numpy as np
    import pyarrow as pa

    if spec.get("small_string"):
        yield from string_table().to_batches(max_chunksize=2)
        return
    batch_rows = min(spec["batch_rows"], 4 if spec["binary"] >= MIB else spec["batch_rows"])
    for start in range(0, spec["rows"], batch_rows):
        marker = np.arange(start, min(start + batch_rows, spec["rows"]), dtype=np.int64)
        ids = (np.where(marker < spec["rows"] * 9 // 10, marker % 5, marker + 100)
               if spec["dense"] else marker)
        columns = {"id": pa.array(ids)}
        columns |= {f"c{i}": pa.array(values(marker, i))
                    for i in range(spec["columns"] - 1)}
        if spec["binary"]:
            columns |= {
                "payload": pa.array([payload(row, spec["binary"]) for row in marker],
                                    type=pa.large_binary()),
                "new_payload": pa.array([b""] * len(marker), type=pa.large_binary()),
                "row_marker": pa.array(marker),
            }
        yield pa.RecordBatch.from_pydict(columns, schema=schema(spec))


def source_batches(spec, directory):
    import numpy as np
    import pyarrow as pa

    if spec.get("small_string"):
        yield from string_table(source=True).to_batches(max_chunksize=2)
        return
    keys = keys_for(spec)
    for start in range(0, spec["source_rows"], spec["batch_rows"]):
        ids = (np.arange(start, min(start + spec["batch_rows"], spec["source_rows"]),
                         dtype=np.int64) if spec["full"]
               else keys[start:start + spec["batch_rows"]])
        if spec["full"]:
            columns = {"id": pa.array(ids)} | {
                f"c{i}": pa.array(values(ids, i, spec["epoch"]))
                for i in range(spec["columns"] - 1)}
        elif spec.get("source_binary"):
            columns = {"id": pa.array(ids), "new_payload": pa.array(
                [payload(row, spec["source_binary"], 1) for row in ids],
                type=pa.large_binary())}
        else:
            columns = {"id": pa.array(ids),
                       "c0": pa.array(np.full(len(ids), -9505, dtype=np.int64)),
                       "c1": pa.array(np.full(len(ids), -10077, dtype=np.int64))}
        batch = pa.RecordBatch.from_pydict(columns, schema=schema(spec, source=True))
        with (directory / "producer.jsonl").open("a") as output:
            output.write(json.dumps(dict(rows=batch.num_rows, bytes=batch.nbytes)) + "\n")
        yield batch


def generate(spec, destination):
    import lance
    import pyarrow as pa

    if destination.exists():
        raise FileExistsError(destination)
    ds = lance.write_dataset(
        pa.RecordBatchReader.from_batches(schema(spec), target_batches(spec)),
        str(destination), data_storage_version="2.2",
        max_rows_per_file=spec["fragment_rows"], max_rows_per_group=spec["batch_rows"])
    metadata = dict(spec=spec, version=ds.version, rows=ds.count_rows(),
                    fragments=len(ds.get_fragments()))
    assert metadata["rows"] == spec["rows"], metadata
    expected_fragments = (spec["rows"] + spec["fragment_rows"] - 1) // spec["fragment_rows"]
    assert metadata["fragments"] == expected_fragments, metadata
    (destination / "fixture.json").write_text(json.dumps(metadata, indent=2))


def validate(spec, directory, unchanged=False):
    import lance
    import numpy as np

    ds = lance.dataset(str(directory / "dataset"))
    expected_schema = schema(spec)
    assert ds.schema.equals(expected_schema), (ds.schema, expected_schema)
    metrics = json.loads((directory / "metrics.json").read_text())
    if unchanged:
        assert ds.version == metrics["snapshot"], (ds.version, metrics["snapshot"])
    if spec.get("small_string"):
        expected = string_table(expected=not unchanged)
        actual = ds.to_table().sort_by("row_marker")
        assert actual.equals(expected), (actual, expected)
        counts = dict(num_updated_rows=0 if unchanged else 2,
                      num_inserted_rows=0, num_deleted_rows=0)
        if not unchanged:
            assert metrics["merge_stats"] == counts, metrics["merge_stats"]
        return dict(validated=True, rows=6, expected_counts=counts,
                    oracle="all-fields-string-null", version=ds.version)
    expected_rows = (max(spec["rows"], spec["source_rows"])
                     if spec["full"] and not unchanged else spec["rows"])
    seen = np.zeros(expected_rows, dtype=np.bool_)
    keys = keys_for(spec)
    count = updated = inserted = 0
    hashes = {name: hashlib.sha256() for name in ds.schema.names}
    for batch in ds.to_batches(batch_size=4 if spec["binary"] >= MIB else 32768,
                               batch_readahead=1):
        ids = batch["id"].to_numpy()
        marker = batch["row_marker"].to_numpy() if spec["binary"] else ids
        assert np.all((marker >= 0) & (marker < expected_rows))
        assert len(np.unique(marker)) == len(marker)
        assert not np.any(seen[marker])
        seen[marker] = True
        expected_ids = (np.where(marker < spec["rows"] * 9 // 10, marker % 5, marker + 100)
                        if spec["dense"] else marker)
        assert np.array_equal(ids, expected_ids)
        hit = ids < spec["source_rows"] if spec["full"] else np.isin(ids, keys)
        if spec.get("predicate_modulus"):
            hit &= marker % spec["predicate_modulus"] == 0
        if unchanged or spec.get("reject_all"):
            hit[:] = False
        updated += int(np.count_nonzero(hit & (marker < spec["rows"])))
        inserted += int(np.count_nonzero(marker >= spec["rows"]))
        for name in batch.schema.names:
            array = batch[name]
            if name.startswith("c"):
                number = int(name[1:])
                expected = values(marker, number)
                if spec["full"]:
                    expected = np.where(hit, values(ids, number, spec["epoch"]), expected)
                elif not spec.get("source_binary") and number < 2:
                    expected = np.where(hit, -9505 if number == 0 else -10077, expected)
                actual = array.to_numpy()
                assert np.array_equal(actual, expected), (name, marker[:5])
                hashes[name].update(actual.tobytes())
            elif name in ("payload", "new_payload"):
                for index, row in enumerate(marker):
                    actual = array[index].as_py()
                    expected = (payload(row, spec["binary"]) if name == "payload"
                                else payload(ids[index], spec["source_binary"], 1)
                                if spec.get("source_binary") and hit[index] else b"")
                    assert hashlib.sha256(actual).digest() == hashlib.sha256(expected).digest(), (name, int(row))
                    hashes[name].update(actual)
            else:
                hashes[name].update(array.to_numpy().tobytes())
        count += len(marker)
    assert count == expected_rows and np.all(seen), (count, expected_rows)
    counts = dict(num_updated_rows=updated, num_inserted_rows=inserted, num_deleted_rows=0)
    if not unchanged:
        assert metrics["merge_stats"] == counts, (metrics["merge_stats"], counts)
        assert ds.version > metrics["snapshot"] if updated + inserted else ds.version >= metrics["snapshot"]
    return dict(validated=True, rows=count, expected_counts=counts,
                hashes={name: value.hexdigest() for name, value in hashes.items()},
                oracle="splitmix64-v1-all-fields", version=ds.version,
                unchanged=unchanged)
