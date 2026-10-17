# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright The Lance Authors

"""Untimed target maintenance around each measured run.

    python prep.py restore <tag>
    python prep.py verify <tier> <expected_rows> <start_version> <versions_added>

``restore`` follows ci_benchmarks/benchmarks/test_merge_insert.py: check out
the tagged pristine version, restore it as the latest, and drop every version
and data file the previous run produced.  Tagged versions are never removed.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta

import lance
import pyarrow.parquet as pq

from common import TARGET_URI, sample_path


def restore(tag: str) -> None:
    ds = lance.dataset(TARGET_URI)
    base_version = ds.tags.list()[tag]["version"]
    restored = ds.checkout_version(base_version)
    restored.restore()
    latest = lance.dataset(TARGET_URI)
    latest.cleanup_old_versions(
        older_than=timedelta(0),
        delete_unverified=True,
        error_if_tagged_old_versions=False,
    )
    print(json.dumps({"restored_tag": tag, "version": latest.version}))


def verify(tier: str, expected_rows: int, start_version: int, versions_added: int):
    ds = lance.dataset(TARGET_URI)
    problems = []
    rows = ds.count_rows()
    if rows != expected_rows:
        problems.append(f"count_rows={rows} expected={expected_rows}")
    if ds.version != start_version + versions_added:
        problems.append(
            f"version={ds.version} expected={start_version}+{versions_added}"
        )

    expected = pq.read_table(sample_path(tier)).sort_by("id")
    ids = ",".join(str(i) for i in expected["id"].to_pylist())
    actual = ds.to_table(filter=f"id IN ({ids})").sort_by("id")
    if actual.num_rows != expected.num_rows:
        problems.append(f"sample rows={actual.num_rows} expected={expected.num_rows}")
    else:
        for column in ("id", "vec", "label", "ts"):
            if not actual[column].equals(expected[column]):
                problems.append(f"sample column {column} differs")
    print(json.dumps({"ok": not problems, "rows": rows, "problems": problems}))


if __name__ == "__main__":
    if sys.argv[1] == "restore":
        restore(sys.argv[2])
    elif sys.argv[1] == "verify":
        verify(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]))
    else:
        raise SystemExit(__doc__)
