"""Stable legacy fixtures plus bounded, targeted counterexample fixtures."""

import hashlib
import json
from pathlib import Path

import legacy_fixtures as legacy


def workloads():
    definitions = legacy.workloads()
    definitions["F64"] = definitions["F16"] | dict(name="F64", rows=64_000_000)
    definitions["R_admission"] = definitions["R"] | dict(
        name="R_admission", rows=1_000_000, fragment_rows=100_000)
    definitions["N_dense"] = definitions["tiny"] | dict(
        name="N_dense", rows=200_000, columns=8, fragment_rows=25_000,
        source_rows=180_000, batch_rows=32_768)
    definitions["V_dense"] = definitions["tiny"] | dict(
        name="V_dense", rows=100_000, columns=6, fragment_rows=10_000,
        source_rows=90_000, batch_rows=256, variable_payload="ordinary",
        min_payload_bytes=128, max_payload_bytes=2048, source_order="shuffled")
    definitions["late_jump"] = definitions["tiny"] | dict(
        name="late_jump", rows=1024, columns=6, fragment_rows=1024,
        source_rows=1024, batch_rows=1024, variable_payload="jump",
        min_payload_bytes=32, max_payload_bytes=1 << 20, change_after=64,
        source_order="ascending")
    return definitions


def schema(spec, source=False):
    import pyarrow as pa

    if not spec.get("variable_payload"):
        return legacy.schema(spec, source)
    fields = [("id", pa.int64()), ("c0", pa.int64()), ("c1", pa.int64())]
    if not source:
        fields += [("keep_text", pa.string()), ("keep_binary", pa.large_binary()),
                   ("row_marker", pa.int64())]
    return pa.schema(fields)


def keys_for(spec):
    import numpy as np

    if spec.get("source_order") == "ascending":
        return np.arange(spec["source_rows"], dtype=np.int64)
    return legacy.keys_for(spec)


def variable_values(marker, spec):
    if spec["variable_payload"] == "jump":
        size = spec["min_payload_bytes"] if marker < spec["change_after"] else spec["max_payload_bytes"]
        text = f"physical-row-{marker}"
    else:
        size = spec["min_payload_bytes"] + (marker * 104729 + 9505) % (
            spec["max_payload_bytes"] - spec["min_payload_bytes"] + 1)
        text = legacy.payload(marker, (size + 1) // 2, epoch=2).hex()[:size]
    binary = legacy.payload(marker, size)
    if spec["variable_payload"] == "ordinary":
        text = None if marker % 17 == 0 else text
        binary = None if marker % 19 == 0 else binary
    return text, binary


def target_batches(spec):
    import numpy as np
    import pyarrow as pa

    if not spec.get("variable_payload"):
        yield from legacy.target_batches(spec)
        return
    batch_rows = 8 if spec["variable_payload"] == "jump" else spec["batch_rows"]
    for start in range(0, spec["rows"], batch_rows):
        ids = np.arange(start, min(start + batch_rows, spec["rows"]), dtype=np.int64)
        payloads = [variable_values(int(row), spec) for row in ids]
        yield pa.RecordBatch.from_pydict(dict(
            id=pa.array(ids), c0=pa.array(legacy.values(ids, 0)), c1=pa.array(legacy.values(ids, 1)),
            keep_text=pa.array([item[0] for item in payloads]),
            keep_binary=pa.array([item[1] for item in payloads], type=pa.large_binary()),
            row_marker=pa.array(ids)), schema=schema(spec))


def source_batches(spec, directory):
    import numpy as np
    import pyarrow as pa

    if spec.get("small_string"):
        for batch in legacy.string_table(source=True).to_batches(max_chunksize=2):
            with (directory / "producer.jsonl").open("a") as output:
                output.write(json.dumps(dict(rows=batch.num_rows, bytes=batch.nbytes)) + "\n")
            yield batch
        return
    if not spec.get("variable_payload"):
        yield from legacy.source_batches(spec, directory)
        return
    keys = keys_for(spec)
    for start in range(0, spec["source_rows"], spec["batch_rows"]):
        ids = keys[start:start + spec["batch_rows"]]
        batch = pa.RecordBatch.from_pydict(dict(
            id=pa.array(ids), c0=pa.array(np.full(len(ids), -9505, dtype=np.int64)),
            c1=pa.array(np.full(len(ids), -10077, dtype=np.int64))), schema=schema(spec, source=True))
        with (directory / "producer.jsonl").open("a") as output:
            output.write(json.dumps(dict(rows=batch.num_rows, bytes=batch.nbytes,
                                        first_key=int(ids[0]), last_key=int(ids[-1]))) + "\n")
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
    metadata = dict(spec=spec, version=ds.version, rows=ds.count_rows(), fragments=len(ds.get_fragments()))
    assert metadata["rows"] == spec["rows"], metadata
    (destination / "fixture.json").write_text(json.dumps(metadata, indent=2))


def validate(spec, directory, unchanged=False):
    import lance
    import numpy as np

    ds = lance.dataset(str(directory / "dataset"))
    assert ds.schema.equals(schema(spec)), (ds.schema, schema(spec))
    original = json.loads((directory / "initial-snapshot.json").read_text())
    metrics_path = directory / "metrics.json"
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    if unchanged:
        assert ds.version == original["version"], (ds.version, original["version"])
    if spec.get("small_string"):
        expected = legacy.string_table(expected=not unchanged)
        actual = ds.to_table().sort_by("row_marker")
        assert actual.equals(expected), (actual, expected)
        counts = dict(num_updated_rows=0 if unchanged else 2, num_inserted_rows=0, num_deleted_rows=0)
        if not unchanged:
            assert metrics["merge_stats"] == counts, metrics["merge_stats"]
            assert ds.version > original["version"], (ds.version, original["version"])
        return dict(validated=True, rows=6, expected_counts=counts, unchanged=unchanged,
                    oracle="all-fields-string-null", version=ds.version,
                    snapshot=original["version"], validated_field_names=ds.schema.names)
    expected_rows = max(spec["rows"], spec["source_rows"]) if spec["full"] and not unchanged else spec["rows"]
    seen = np.zeros(expected_rows, dtype=np.bool_)
    keys = keys_for(spec)
    key_bitmap = None
    if keys is not None and not spec["dense"]:
        key_bitmap = np.zeros(spec["rows"], dtype=np.bool_)
        key_bitmap[keys] = True
    hashes = {name: hashlib.sha256() for name in ds.schema.names}
    count = updated = inserted = 0
    batch_rows = 4 if spec["binary"] >= 1 << 20 or spec.get("variable_payload") == "jump" else 32768
    for batch in ds.to_batches(batch_size=batch_rows, batch_readahead=1):
        ids = batch["id"].to_numpy()
        marker = batch["row_marker"].to_numpy() if "row_marker" in batch.schema.names else ids
        assert np.all((marker >= 0) & (marker < expected_rows))
        assert len(np.unique(marker)) == len(marker) and not np.any(seen[marker])
        seen[marker] = True
        expected_ids = np.where(marker < spec["rows"] * 9 // 10, marker % 5, marker + 100) if spec["dense"] else marker
        assert np.array_equal(ids, expected_ids)
        hit = ids < spec["source_rows"] if spec["full"] else np.isin(ids, keys) if key_bitmap is None else key_bitmap[ids]
        if spec.get("predicate_modulus"):
            hit &= marker % spec["predicate_modulus"] == 0
        if unchanged or spec.get("reject_all"):
            hit[:] = False
        updated += int(np.count_nonzero(hit & (marker < spec["rows"])))
        inserted += int(np.count_nonzero(marker >= spec["rows"]))
        variable = [variable_values(int(row), spec) for row in marker] if spec.get("variable_payload") else None
        for name in batch.schema.names:
            array = batch[name]
            if name.startswith("c"):
                number = int(name[1:])
                expected = legacy.values(marker, number)
                if spec["full"]:
                    expected = np.where(hit, legacy.values(marker, number, spec["epoch"]), expected)
                elif name in ("c0", "c1") and not spec.get("source_binary"):
                    expected = np.where(hit, -9505 if name == "c0" else -10077, expected)
                assert np.array_equal(array.to_numpy(), expected), name
            elif name in ("payload", "new_payload"):
                for index, value in enumerate(array.to_pylist()):
                    expected = legacy.payload(marker[index], spec["binary"]) if name == "payload" else (
                        legacy.payload(ids[index], spec["source_binary"], 1) if spec.get("source_binary") and hit[index] else b"")
                    assert value == expected, (name, int(marker[index]))
            elif name in ("keep_text", "keep_binary"):
                assert array.to_pylist() == [item[0 if name == "keep_text" else 1] for item in variable], name
            elif name == "row_marker":
                assert np.array_equal(array.to_numpy(), marker)
            elif name != "id":
                raise AssertionError(f"No oracle for field {name}")
            if name in ("payload", "new_payload", "keep_text", "keep_binary"):
                for value in array.to_pylist():
                    if value is None:
                        hashes[name].update(b"\x00")
                        continue
                    encoded = value.encode() if isinstance(value, str) else value
                    hashes[name].update(b"\x01")
                    hashes[name].update(len(encoded).to_bytes(8, "little"))
                    hashes[name].update(encoded)
            else:
                hashes[name].update(array.to_numpy().tobytes())
        count += batch.num_rows
    assert count == expected_rows and np.all(seen), (count, expected_rows)
    counts = dict(num_updated_rows=updated, num_inserted_rows=inserted, num_deleted_rows=0)
    if not unchanged:
        assert metrics["merge_stats"] == counts, (metrics.get("merge_stats"), counts)
        assert ds.version > original["version"] if any(counts.values()) else ds.version >= original["version"]
    return dict(validated=True, rows=count, expected_counts=counts,
                hashes={name: value.hexdigest() for name, value in hashes.items()},
                oracle="deterministic-v2-all-fields", version=ds.version,
                snapshot=original["version"], unchanged=unchanged,
                validated_field_names=ds.schema.names)
