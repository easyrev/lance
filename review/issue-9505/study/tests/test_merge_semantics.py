"""Public-API merge checks around the frozen B source-preparation row boundary."""

import lance
import pyarrow as pa
import pytest


ROW_LIMIT = 128 * 1024
PREFIX_ROWS = ROW_LIMIT + 1


@pytest.fixture
def target(tmp_path):
    schema = pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("value", pa.int64()),
            pa.field("payload", pa.string()),
            pa.field("enabled", pa.bool_()),
        ],
        metadata={b"test": b"merge-source-boundary"},
    )
    initial = pa.table(
        {
            "id": [0, 1, 2, 3],
            "value": [10, 20, 30, 40],
            "payload": ["zero", None, "two", "three"],
            "enabled": [True, False, None, True],
        },
        schema=schema,
    )
    uri = tmp_path / "target.lance"
    dataset = lance.write_dataset(
        initial, uri, max_rows_per_file=2, data_storage_version="2.2"
    )
    assert len(dataset.get_fragments()) == 2
    return dataset, uri, initial


def _crossing_prefix(schema, value):
    prefix = pa.RecordBatch.from_arrays(
        [
            pa.array(range(PREFIX_ROWS), type=pa.int64()),
            pa.array([value] * PREFIX_ROWS, type=pa.int64()),
        ],
        schema=schema,
    )
    assert prefix.num_rows > ROW_LIMIT
    return prefix


def _assert_snapshot_unchanged(dataset, uri, initial, version, history):
    reloaded = lance.dataset(uri)
    assert reloaded.version == version
    assert reloaded.latest_version == version
    assert tuple(item["version"] for item in reloaded.versions()) == history
    for view in (dataset, reloaded, lance.dataset(uri, version=version)):
        assert view.version == version
        assert view.to_table().sort_by("id").equals(initial, check_metadata=True)


def test_tail_source_error_after_row_bound_preserves_snapshot(target):
    dataset, uri, initial = target
    version = dataset.version
    history = tuple(item["version"] for item in dataset.versions())
    schema = initial.select(["id", "value"]).schema
    prefix = _crossing_prefix(schema, 100)
    tail = pa.RecordBatch.from_arrays(
        [pa.array([PREFIX_ROWS], pa.int64()), pa.array([200], pa.int64())],
        schema=schema,
    )
    events = []

    def source():
        events.append("crossing_prefix")
        yield prefix
        events.append("tail_batch")
        yield tail
        events.append("tail_error")
        raise RuntimeError("source failed after the prefetch row boundary")

    reader = pa.RecordBatchReader.from_batches(schema, source())
    with pytest.raises(OSError, match="source failed after the prefetch row boundary"):
        (
            dataset.merge_insert("id")
            .use_index(False)
            .write_mode("rewrite_rows")
            .conflict_retries(0)
            .when_matched_update_all()
            .execute(reader)
        )
    assert events == ["crossing_prefix", "tail_batch", "tail_error"]
    _assert_snapshot_unchanged(dataset, uri, initial, version, history)


def test_duplicate_modification_across_row_bound_fails_without_commit(target):
    dataset, uri, initial = target
    version = dataset.version
    history = tuple(item["version"] for item in dataset.versions())
    schema = initial.select(["id", "value"]).schema
    prefix = _crossing_prefix(schema, 100)
    duplicate = pa.RecordBatch.from_arrays(
        [pa.array([0], pa.int64()), pa.array([200], pa.int64())], schema=schema
    )
    events = []

    def source():
        events.append("crossing_prefix")
        yield prefix
        events.append("duplicate_tail")
        yield duplicate

    reader = pa.RecordBatchReader.from_batches(schema, source())
    with pytest.raises(
        OSError, match=r"(?s)Ambiguous merge insert.*multiple source rows"
    ):
        (
            dataset.merge_insert("id")
            .use_index(False)
            .write_mode("rewrite_rows")
            .conflict_retries(0)
            .when_matched_update_all()
            .execute(reader)
        )
    assert events == ["crossing_prefix", "duplicate_tail"]
    _assert_snapshot_unchanged(dataset, uri, initial, version, history)


def test_only_actual_update_counts_across_row_bound(target):
    dataset, uri, initial = target
    version = dataset.version
    history = tuple(item["version"] for item in dataset.versions())
    schema = initial.select(["id", "value"]).schema
    # Every matched prefix row fails the condition. The duplicate key in the
    # tail is the only row that actually modifies its target.
    prefix = _crossing_prefix(schema, 5)
    duplicate = pa.RecordBatch.from_arrays(
        [pa.array([0], pa.int64()), pa.array([99], pa.int64())], schema=schema
    )
    events = []

    def source():
        events.append("crossing_prefix")
        yield prefix
        events.append("duplicate_tail")
        yield duplicate

    reader = pa.RecordBatchReader.from_batches(schema, source())
    stats = (
        dataset.merge_insert("id")
        .use_index(False)
        .write_mode("rewrite_rows")
        .conflict_retries(0)
        .when_matched_update_all("source.value > target.value")
        .execute(reader)
    )
    assert events == ["crossing_prefix", "duplicate_tail"]
    assert stats == {
        "num_inserted_rows": 0,
        "num_updated_rows": 1,
        "num_deleted_rows": 0,
    }
    expected = pa.table(
        {
            "id": [0, 1, 2, 3],
            "value": [99, 20, 30, 40],
            "payload": ["zero", None, "two", "three"],
            "enabled": [True, False, None, True],
        },
        schema=initial.schema,
    )
    reloaded = lance.dataset(uri)
    assert reloaded.version == version + 1
    assert tuple(item["version"] for item in reloaded.versions()) == history + (
        version + 1,
    )
    for view in (dataset, reloaded):
        assert view.to_table().sort_by("id").equals(expected, check_metadata=True)
    assert (
        lance.dataset(uri, version=version)
        .to_table()
        .sort_by("id")
        .equals(initial, check_metadata=True)
    )
