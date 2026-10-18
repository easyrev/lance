"""Small forced Early/Late oracles. Run in the C checkout after installation."""

import json
import os
import re
from pathlib import Path

import lance
import pyarrow as pa

ROOT = Path(__file__).resolve().parent / "diagnostics" / "semantics"


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    os.environ["LANCE_MERGE_DIAGNOSTICS"] = "1"
    for mode in ["Ccore", "Clate"]:
        os.environ["LANCE_MERGE_EXPERIMENT"] = mode
        for action in ["update", "condition", "delete", "fail", "error", "empty"]:
            directory = ROOT / f"{mode}-{action}"
            directory.mkdir()
            os.environ["LANCE_MERGE_EVIDENCE"] = str(directory / "candidate.jsonl")
            target = pa.table(
                {
                    "id": pa.array([1, 2, 1, None, 3, 4], type=pa.int64()),
                    "value": [10, 20, 30, 40, 50, 60],
                    "old": [b"A", None, b"C", b"D", b"E", b"F"],
                    "row_marker": [0, 1, 2, 3, 4, 5],
                }
            )
            ds = lance.write_dataset(
                target,
                str(directory / "dataset"),
                max_rows_per_file=2,
                data_storage_version="2.2",
                enable_stable_row_ids=True,
            )
            source = pa.table(
                {
                    "id": pa.array([2, 1, 7, None], type=pa.int64()),
                    "value": [200, 100, 700, 800],
                }
            )
            if action == "empty":
                source = source.slice(0, 0)
            builder = ds.merge_insert("id").use_index(False).conflict_retries(0)
            if action == "delete":
                builder = builder.when_matched_delete()
            elif action == "fail":
                builder = builder.when_matched_fail()
            elif action == "condition":
                builder = builder.when_matched_update_all("target.value < 25")
            else:
                builder = builder.when_matched_update_all()
            if action in ("update", "condition"):
                builder = builder.when_not_matched_insert_all()
            version = ds.version
            if action == "error":

                def broken():
                    yield pa.record_batch(
                        {
                            "id": pa.array([999] * 131073, type=pa.int64()),
                            "value": pa.array([1] * 131073, type=pa.int64()),
                        }
                    )
                    raise RuntimeError("source-test-failure")

                incoming = pa.RecordBatchReader.from_batches(source.schema, broken())
            else:
                incoming = source.to_reader(max_chunksize=1)
            try:
                stats = builder.execute(incoming)
            except Exception as error:
                assert action in ("error", "fail"), (mode, action, str(error))
                expected = (
                    "source-test-failure" if action == "error" else "found matching row"
                )
                assert expected in str(error), str(error)
                unchanged = lance.dataset(str(directory / "dataset"))
                assert unchanged.version == version
                assert unchanged.to_table().equals(target)
                assert_payload_path(directory, mode, 0)
                (directory / "result.json").write_text(
                    json.dumps(
                        {
                            "passed": True,
                            "expected_error": str(error),
                            "no_commit": True,
                        }
                    )
                )
                continue
            assert action not in ("fail", "error")
            actual = lance.dataset(str(directory / "dataset")).to_table().to_pylist()
            original = target.to_pylist()
            expected = []
            for row in original:
                match = row["id"] in (1, 2)
                if action == "delete" and match:
                    continue
                if match and (
                    action == "update" or action == "condition" and row["value"] < 25
                ):
                    row["value"] = 100 if row["id"] == 1 else 200
                expected.append(row)
            if action in ("update", "condition"):
                expected += [
                    {"id": 7, "value": 700, "old": None, "row_marker": None},
                    {"id": None, "value": 800, "old": None, "row_marker": None},
                ]

            def canonical(rows):
                return sorted(
                    json.dumps(row, sort_keys=True, default=lambda value: value.hex())
                    for row in rows
                )

            assert canonical(actual) == canonical(expected), (
                mode,
                action,
                actual,
                expected,
            )
            assert_payload_path(
                directory, mode, {"update": 3, "condition": 2}.get(action, 0)
            )
            (directory / "result.json").write_text(
                json.dumps({"passed": True, "stats": stats, "rows": len(actual)})
            )
    print("Early/Late semantic cases passed", flush=True)


def assert_payload_path(directory, mode, expected_rows):
    events = [
        json.loads(line)
        for line in (directory / "candidate.jsonl").read_text().splitlines()
    ]
    plans = [
        event["plan"]
        for event in events
        if event["phase"] in ("physical_plan", "operator_metrics")
    ]
    assert any("MergePayload:" in plan for plan in plans) == (mode == "Clate")
    if mode == "Clate":
        metrics = [
            event["plan"] for event in events if event["phase"] == "operator_metrics"
        ]
        counts = [
            int(count)
            for plan in metrics
            for count in re.findall(r"payload_take_rows=(\d+)", plan)
        ]
        assert counts and counts[-1] == expected_rows, (expected_rows, counts, metrics)


if __name__ == "__main__":
    main()
