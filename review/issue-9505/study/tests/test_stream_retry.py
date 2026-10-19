"""Exercise replay of a one-shot partial source after a real commit conflict."""

import lance
import pyarrow as pa
import pytest


def test_stream_retry_refreshes_partial_payload(tmp_path):
    schema = pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("value", pa.int64()),
            pa.field("payload", pa.string()),
            pa.field("enabled", pa.bool_()),
        ]
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
    stale = lance.write_dataset(
        initial, uri, max_rows_per_file=2, data_storage_version="2.2"
    )
    assert len(stale.get_fragments()) == 2
    first_version = stale.version

    def merge(retries):
        return (
            stale.merge_insert("id")
            .when_matched_update_all()
            .use_index(False)
            .write_mode("rewrite_rows")
            .conflict_retries(retries)
        )

    # Both builders capture the old snapshot before the competing writer commits.
    fail_fast = merge(0)
    retry_once = merge(1)

    def row_address(dataset):
        return dataset.to_table(
            columns=["id"], filter="id = 0", with_row_address=True
        )["_rowaddr"][0].as_py()

    old_address = row_address(stale)
    competing = lance.dataset(uri)
    replacement = pa.table(
        {
            "id": [0],
            "value": [11],
            "payload": ["concurrent"],
            "enabled": [False],
        },
        schema=schema,
    )
    competing_stats = (
        competing.merge_insert("id")
        .when_matched_update_all()
        .use_index(False)
        .write_mode("rewrite_rows")
        .conflict_retries(0)
        .execute(replacement)
    )
    assert competing_stats == {
        "num_inserted_rows": 0,
        "num_updated_rows": 1,
        "num_deleted_rows": 0,
    }
    assert stale.version == first_version
    assert competing.version == first_version + 1
    assert row_address(competing) != old_address
    after_competing = pa.table(
        {
            "id": [0, 1, 2, 3],
            "value": [11, 20, 30, 40],
            "payload": ["concurrent", None, "two", "three"],
            "enabled": [False, False, None, True],
        },
        schema=schema,
    )
    assert competing.to_table().sort_by("id").equals(after_competing)

    partial = pa.table(
        {"id": [0, 3], "value": [100, 400]},
        schema=initial.select(["id", "value"]).schema,
    )

    def make_reader():
        events = []

        def batches():
            for index, batch in enumerate(partial.to_batches(max_chunksize=1)):
                events.append(index)
                yield batch
            events.append("eof")

        return pa.RecordBatchReader.from_batches(partial.schema, batches()), events

    # Establish that this stale operation really conflicts and cannot just rebase.
    reader, events = make_reader()
    with pytest.raises(OSError, match="Attempted 0 retries"):
        fail_fast.execute(reader)
    assert events == [0, 1, "eof"]
    current = lance.dataset(uri)
    assert current.version == first_version + 1
    assert current.to_table().sort_by("id").equals(after_competing)
    assert sorted(item["version"] for item in current.versions()) == [
        first_version,
        first_version + 1,
    ]

    # A new one-shot reader is consumed once; the engine must replay its saved data.
    reader, events = make_reader()
    stats = retry_once.execute(reader)
    assert events == [0, 1, "eof"]
    assert stats == {
        "num_inserted_rows": 0,
        "num_updated_rows": 2,
        "num_deleted_rows": 0,
    }
    expected = pa.table(
        {
            "id": [0, 1, 2, 3],
            "value": [100, 20, 30, 400],
            "payload": ["concurrent", None, "two", "three"],
            "enabled": [False, False, None, True],
        },
        schema=schema,
    )
    latest = lance.dataset(uri)
    assert latest.version == first_version + 2
    assert stale.version == latest.version
    for view in (stale, latest):
        assert view.to_table().sort_by("id").equals(expected)
    assert sorted(item["version"] for item in latest.versions()) == [
        first_version,
        first_version + 1,
        first_version + 2,
    ]
    assert (
        lance.dataset(uri, version=first_version)
        .to_table()
        .sort_by("id")
        .equals(initial)
    )
    assert (
        lance.dataset(uri, version=first_version + 1)
        .to_table()
        .sort_by("id")
        .equals(after_competing)
    )
